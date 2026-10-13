"""Verificación de SOLO LECTURA del backend contra la base configurada en .env.

Levanta la app en memoria (sin servidor), emite un token para el primer ADMIN
y llama a todos los endpoints GET. La sesión de PostgreSQL se fuerza a solo
lectura (default_transaction_read_only=on): aunque algo intentara escribir,
la base lo rechazaría.

Uso (en la carpeta del backend, con el .env de producción):
    python verificar_produccion.py
Sale con código 0 si todo responde 200, y con 1 si algo falla.
"""
import logging
import os
import sys

os.environ["PGOPTIONS"] = (os.environ.get("PGOPTIONS", "") + " -c default_transaction_read_only=on").strip()
logging.disable(logging.CRITICAL)

import psycopg2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app import app  # noqa: E402
from auth import crear_token  # noqa: E402


def main() -> int:
    conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"), connect_timeout=10)
    with conn, conn.cursor() as cur:
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "on":
            print("ERROR: la sesión no quedó en solo lectura; se aborta.")
            return 1
        cur.execute("SELECT current_database(), inet_server_addr()")
        bd, addr = cur.fetchone()
        cur.execute("SELECT to_regclass('printers') IS NOT NULL AND to_regclass('printer_readings') IS NOT NULL")
        tablas_impresoras = cur.fetchone()[0]
        cur.execute("SELECT id, username, role FROM users WHERE role = 'ADMIN' ORDER BY id LIMIT 1")
        admin = cur.fetchone()
        cur.execute("SELECT count(*), count(*) FILTER (WHERE password LIKE '$2%%') FROM users")
        total_users, bcrypt_users = cur.fetchone()
        cur.execute("SELECT cedula FROM people WHERE cedula IS NOT NULL LIMIT 1")
        fila = cur.fetchone()
    conn.close()

    print(f"BD: {bd} ({addr or 'local'}) · sesión de solo lectura")
    print(f"Tablas de impresoras (migración 005): {'sí' if tablas_impresoras else 'NO — falta aplicar sql/005_impresoras.py --aplicar'}")
    print(f"Usuarios: {total_users}, con bcrypt: {bcrypt_users}"
          + ("" if bcrypt_users == total_users else " (falta sql/004_hashear_passwords.py --aplicar, después de desplegar)"))
    if not admin:
        print("ERROR: no hay ningún usuario ADMIN.")
        return 1

    cliente = TestClient(app)
    cab = {"Authorization": "Bearer " + crear_token(*admin)}
    rutas = ["/equipos/vista/inventario-general", "/equipos/vista/equipo-completo", "/equipos/vista/computadora-asignada",
             "/equipos/catalogos/statuses", "/equipos/companies", "/equipos/people", "/equipos/hardware",
             "/equipos/accessory-types", "/equipos/accessories/disponibles", "/equipos/computers/disponibles",
             "/impresoras", "/impresoras/resumen"]
    if fila:
        rutas += [f"/equipos/vista/equipo-completo/{fila[0]}", f"/equipos/accesorios/persona/{fila[0]}"]
    rutas += [r.path for r in app.routes
              if getattr(r, "path", "").startswith("/mantenimiento") and "GET" in getattr(r, "methods", set())
              and "{" not in r.path]

    fallos = 0
    for ruta in rutas:
        r = cliente.get(ruta, headers=cab)
        n = f" ({len(r.json())} filas)" if r.status_code == 200 and isinstance(r.json(), list) else ""
        print(f"  {'OK ' if r.status_code == 200 else 'ERR'} {r.status_code} {ruta}{n}")
        fallos += r.status_code != 200
    sin_token = cliente.get("/equipos/companies").status_code
    print(f"  {'OK ' if sin_token == 401 else 'ERR'} {sin_token} /equipos/companies sin token (debe ser 401)")
    fallos += sin_token != 401

    print("RESULTADO:", "todo correcto" if not fallos else f"{fallos} comprobaciones fallaron")
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
