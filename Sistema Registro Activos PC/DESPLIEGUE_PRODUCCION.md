# Despliegue a producción: KEYCID365 (rama `mejoras-auditoria-impresoras`)

Servidor de la app: **192.168.20.4** (backend en el puerto 7001, frontend en el 4001) · Base de datos: **192.168.20.3:5432/keycid365**

## Estado verificado de la BD de producción (2026-10-13, en solo lectura)
- Los 15 endpoints de consulta del backend nuevo responden 200 con los datos reales (212 equipos, 618 personas, 92 mantenimientos).
- Están todos los estados que usa el código: DISPONIBLE, ASIGNADO, BAJA, ELIMINADO y ACTIVO.
- **Faltan** las tablas de impresoras: hay que aplicar la migración 005. El simulacro rellenará 27 impresoras, 11 de ellas detectadas como de color.
- Hay 2 usuarios (`admin`, `Sistemas`), los dos con la contraseña en texto plano. El backend nuevo los acepta (es compatible) hasta aplicar la migración 004.

## Orden de despliegue (respétalo)

### 0. Respaldo de la BD
```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -h 192.168.20.3 -U <usuario> -d keycid365 -Fc -f "keycid365_antes_despliegue_$(Get-Date -f yyyyMMdd_HHmm).dump"
```

### 1. Migración 005 (impresoras): solo AÑADE tablas; el sistema actual sigue funcionando
```powershell
cd backend
python sql\005_impresoras.py              # simulacro: revisa la salida
python sql\005_impresoras.py --aplicar    # escribe SI para confirmar
```
Reversión, si hiciera falta (pierde las lecturas cargadas): `DROP TABLE printer_readings; DROP TABLE printers;`

### 2. Backend
1. Detén el backend actual (puerto 7001) y respalda la carpeta `F:\KeyCi360\KEYCID365\backend`.
2. Copia el código nuevo de `Activos_LP_CID (1)/Activos_LP_CID/`. **Conserva el `.env` del servidor** y añádele estas líneas (usa `.env.example` como guía):
   ```
   JWT_SECRET=<genera uno nuevo: python -c "import secrets; print(secrets.token_urlsafe(48))">
   CORS_EXTRA_ORIGINS=http://192.168.20.4:4001
   ENABLE_DOCS=
   ```
   - `JWT_SECRET` debe tener al menos 32 caracteres; si no, la app no arranca. No reutilices el de desarrollo.
   - Con `ENABLE_DOCS` vacío, `/docs` queda desactivado en producción. Escribe `true` solo si de verdad lo necesitas.
3. Instala las dependencias nuevas (bcrypt y PyJWT): `pip install -r requirements.txt`
4. Verifica en **solo lectura** antes de encender:
   ```powershell
   python verificar_produccion.py    # debe terminar en "RESULTADO: todo correcto"
   ```
5. Enciende el backend. Usa **un solo proceso y sin `--reload`**, porque el límite de intentos de login vive en memoria:
   ```powershell
   uvicorn app:app --host 192.168.20.4 --port 7001
   ```

### 3. Frontend: compílalo con la URL del API
La CSP del `index.html` solo permite llamar a la URL definida **al compilar**. Si compilas sin ella, el navegador bloquea el login.
```powershell
cd kc360
npm install
$env:REACT_APP_API_URL="http://192.168.20.4:7001"; npx react-scripts build
```
Copia `build\` al servidor y sírvelo con `serve`, que lee `build\serve.json` (cabeceras anti-clickjacking):
```powershell
npx serve -s build -l 4001
```
Comprueba las cabeceras con `curl -I http://192.168.20.4:4001`: debe aparecer `X-Frame-Options: DENY`.

### 4. Prueba de humo
- Entra en http://192.168.20.4:4001 con `admin` o `Sistemas`.
- Revisa el Dashboard, Equipos, Impresoras, Mantenimiento y Personal.
- Repite `python verificar_produccion.py`.

### 5. Migración 004 (contraseñas a bcrypt): SOLO después de que el backend nuevo esté funcionando
El backend anterior compara texto plano: si conviertes antes, los logins del sistema viejo dejan de funcionar.
```powershell
python sql\004_hashear_passwords.py              # simulacro
python sql\004_hashear_passwords.py --aplicar
```
Las contraseñas no cambian: siguen siendo las mismas, solo que se guardan cifradas.

## Después del despliegue
- **Cambia la contraseña de la BD** (`DB_PASSWORD`): estuvo en el historial del repositorio público. Después actualiza el `.env` del servidor.
- **Pon en privado** el repositorio `KevinF13/KeyCi360-Completo`.
- **Completa los datos de las impresoras** desde el módulo Impresoras → Editar: IP, hostname, área y empresa. También marca como "a color" la Epson L575, porque la detección automática la dejó como monocromo.
- **Reversión:** detén los servicios, restaura las carpetas respaldadas y, si hace falta, restaura el dump del paso 0.
