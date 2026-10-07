"""
Renombra la base de datos del sistema: inventario_activos -> keycid365.

IMPORTANTE: PostgreSQL no permite renombrar una base con conexiones abiertas. El script
bloquea conexiones nuevas, cierra las existentes (incluida la app publicada en 192.168.20.4,
DBeaver, pgAdmin...), renombra y vuelve a permitir conexiones.
Después hay que cambiar DB_NAME=keycid365 en TODOS los servidores que usan la base
(este .env se actualiza solo; el de 192.168.20.4 hay que cambiarlo a mano) y reiniciar sus backends.

Uso (desde la carpeta del backend):
    python sql/003_renombrar_bd_keycid365.py              -> muestra conexiones y lo que haría, no cambia nada
    python sql/003_renombrar_bd_keycid365.py --confirmar  -> renombra y actualiza el .env
    python sql/003_renombrar_bd_keycid365.py --revertir --confirmar  -> vuelve a inventario_activos
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
NOMBRE_ANTERIOR = "inventario_activos"
NOMBRE_NUEVO = "keycid365"


def conectar_mantenimiento():
    # Se conecta a la base "postgres": no se puede renombrar la base a la que uno está conectado
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname="postgres",
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def existe(cur, nombre):
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre,))
    return cur.fetchone() is not None


def conexiones(cur, nombre):
    cur.execute("""
        SELECT pid, usename, COALESCE(NULLIF(application_name, ''), '(sin nombre)'), client_addr, state
        FROM pg_stat_activity
        WHERE datname = %s AND pid <> pg_backend_pid()
        ORDER BY client_addr
    """, (nombre,))
    return cur.fetchall()


def actualizar_env(env_path, nombre):
    texto = env_path.read_text(encoding="utf-8")
    nuevo, n = re.subn(r"(?m)^(\s*DB_NAME\s*=\s*).*$", rf"\g<1>{nombre}", texto)
    if n != 1:
        print(f"  AVISO: no se encontró una única línea DB_NAME en {env_path}; actualícela a mano.")
        return
    respaldo = env_path.with_name(env_path.name + ".bak")
    shutil.copy2(env_path, respaldo)
    env_path.write_text(nuevo, encoding="utf-8")
    print(f"  {env_path.name}: DB_NAME={nombre} (respaldo en {respaldo.name})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirmar", action="store_true", help="ejecuta el cambio (sin esto solo muestra)")
    ap.add_argument("--revertir", action="store_true", help=f"renombra de vuelta a {NOMBRE_ANTERIOR}")
    ap.add_argument("--env-file", default=str(RAIZ / ".env"), help="archivo .env a actualizar")
    args = ap.parse_args()

    env_path = Path(args.env_file)
    load_dotenv(env_path)  # no sobreescribe variables DB_* ya definidas

    origen, destino = (NOMBRE_NUEVO, NOMBRE_ANTERIOR) if args.revertir else (NOMBRE_ANTERIOR, NOMBRE_NUEVO)

    conn = conectar_mantenimiento()
    conn.autocommit = True  # ALTER DATABASE no puede ir dentro de una transacción
    cur = conn.cursor()

    print(f"Servidor: {os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}")
    if not existe(cur, origen):
        sys.exit(f"ABORTADO: no existe la base '{origen}'.")
    if existe(cur, destino):
        sys.exit(f"ABORTADO: ya existe una base llamada '{destino}'.")

    activas = conexiones(cur, origen)
    print(f"Renombrar '{origen}' -> '{destino}'. Conexiones abiertas que se cerrarán: {len(activas)}")
    for pid, usuario, app, ip, estado in activas:
        print(f"  pid {pid}: {usuario} · {app} · {ip or 'local'} · {estado}")

    if not args.confirmar:
        print("Vista previa: no se cambió nada. Agregue --confirmar para ejecutar.")
        return

    cur.execute(f'ALTER DATABASE "{origen}" WITH ALLOW_CONNECTIONS false')
    try:
        cur.execute("""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
        """, (origen,))
        cur.execute(f'ALTER DATABASE "{origen}" RENAME TO "{destino}"')
    except Exception:
        cur.execute(f'ALTER DATABASE "{origen}" WITH ALLOW_CONNECTIONS true')
        raise
    cur.execute(f'ALTER DATABASE "{destino}" WITH ALLOW_CONNECTIONS true')
    conn.close()
    print(f"Base renombrada a '{destino}'.")

    actualizar_env(env_path, destino)
    print("Pendiente: cambiar DB_NAME en el servidor 192.168.20.4 (y cualquier otro cliente) y reiniciar los backends.")


if __name__ == "__main__":
    main()
