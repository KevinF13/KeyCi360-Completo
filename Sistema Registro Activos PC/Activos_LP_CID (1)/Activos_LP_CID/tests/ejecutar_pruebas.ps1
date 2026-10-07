# Ejecuta las pruebas de la API contra una COPIA local y desechable de la base real.
#
#   1. Crea (si no existe) un clúster PostgreSQL privado en $env:TEMP\keycid365_pruebas (puerto 5433).
#   2. Copia la base real con pg_dump (solo lectura) y la restaura como keycid365_test.
#   3. Corre pytest apuntando a esa copia.
#
# Uso:  powershell -ExecutionPolicy Bypass -File tests\ejecutar_pruebas.ps1
param(
    [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin",
    [int]$Puerto = 5433,
    [string]$Dir = (Join-Path $env:TEMP "keycid365_pruebas")
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$datos = Join-Path $Dir "pgdata"
$dump = Join-Path $Dir "copia.dump"
$bdPrueba = "keycid365_test"

# Credenciales de la base real (solo para el pg_dump)
$envReal = @{}
Get-Content (Join-Path $raiz ".env") | Where-Object { $_ -match "^\s*([A-Z_]+)\s*=\s*(.*)$" } |
    ForEach-Object { $envReal[$Matches[1]] = $Matches[2].Trim() }

New-Item -ItemType Directory -Force $Dir | Out-Null
if (-not (Test-Path $datos)) {
    & "$PgBin\initdb.exe" -D $datos -U postgres -A trust -E UTF8 --locale=C | Out-Null
}
& "$PgBin\pg_isready.exe" -h localhost -p $Puerto | Out-Null
if ($LASTEXITCODE -ne 0) {
    # Start-Process sin -Wait: el servidor no hereda la salida del script (si la hereda, o con -Wait, el script no termina)
    Start-Process -FilePath "$PgBin\pg_ctl.exe" -WindowStyle Hidden -ArgumentList @(
        "-D", "`"$datos`"", "-o", "`"-p $Puerto -c listen_addresses=localhost`"",
        "-l", "`"$(Join-Path $Dir 'pg.log')`"", "start"
    )
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        & "$PgBin\pg_isready.exe" -h localhost -p $Puerto | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
    }
    if ($LASTEXITCODE -ne 0) { throw "El servidor de pruebas no arrancó (ver $Dir\pg.log)" }
}

Write-Host "Copiando la base real (solo lectura)..."
$env:PGPASSWORD = $envReal["DB_PASSWORD"]
& "$PgBin\pg_dump.exe" -h $envReal["DB_HOST"] -p $envReal["DB_PORT"] -U $envReal["DB_USER"] -d $envReal["DB_NAME"] -Fc --no-owner --no-privileges -f $dump
Remove-Item Env:PGPASSWORD
if ($LASTEXITCODE -ne 0) { throw "pg_dump falló" }

& "$PgBin\dropdb.exe" -h localhost -p $Puerto -U postgres --if-exists $bdPrueba
& "$PgBin\createdb.exe" -h localhost -p $Puerto -U postgres $bdPrueba
& "$PgBin\pg_restore.exe" -h localhost -p $Puerto -U postgres -d $bdPrueba --no-owner --no-privileges $dump
# La copia hereda las secuencias de producción; se alinean para que las pruebas no fallen por eso
& "$PgBin\psql.exe" -h localhost -p $Puerto -U postgres -d $bdPrueba -q -c "SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 0) + 1 FROM users), false)" | Out-Null

$env:TEST_DB_HOST = "localhost"
$env:TEST_DB_PORT = "$Puerto"
$env:TEST_DB_NAME = $bdPrueba
$env:TEST_DB_USER = "postgres"
$env:TEST_DB_PASSWORD = ""
Push-Location $raiz
try { python -m pytest tests -v -rx -p no:cacheprovider } finally { Pop-Location }
