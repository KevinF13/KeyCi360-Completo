"""
Convierte a bcrypt las contraseñas en texto plano de la tabla users.

Idempotente: solo toca filas cuyo password NO empieza por "$2" (ya bcrypt).
Por defecto es un simulacro (dry-run): no modifica nada y solo muestra cuántas filas cambiaría
(nunca imprime contraseñas).

IMPORTANTE: ejecutar DESPUÉS de desplegar el backend nuevo (que verifica bcrypt y texto plano).
El sistema anterior compara texto plano y dejaría de aceptar los logins una vez hasheadas.

Uso (desde la carpeta del backend, con las variables DB_* del .env o del entorno):
    python sql/004_hashear_passwords.py             -> simulacro
    python sql/004_hashear_passwords.py --aplicar   -> pide confirmación y aplica
    python sql/004_hashear_passwords.py --aplicar --si   -> aplica sin preguntar
"""
import argparse
import os
import sys
from pathlib import Path

import bcrypt
import psycopg2
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="Aplica los cambios (por defecto solo simulacro)")
    ap.add_argument("--si", action="store_true", help="No pedir confirmación interactiva")
    args = ap.parse_args()

    load_dotenv(RAIZ / ".env")  # no sobreescribe variables ya definidas en el entorno
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), inet_server_addr()")
            bd, addr = cur.fetchone()
            cur.execute("SELECT id, username, password FROM users "
                        "WHERE password IS NOT NULL AND password <> '' AND password NOT LIKE '$2%' ORDER BY id")
            pendientes = cur.fetchall()
            cur.execute("SELECT count(*) FROM users")
            total = cur.fetchone()[0]

        print(f"BD: {bd} ({addr or 'socket local'})  usuarios: {total}  con texto plano: {len(pendientes)}")
        for uid, username, _ in pendientes:
            print(f"  - id={uid} usuario={username}")

        # bcrypt solo admite 72 bytes: más largas no se truncan en silencio, se omiten y se avisa
        largas = [p for p in pendientes if len(p[2].encode("utf-8")) > 72]
        convertibles = [p for p in pendientes if len(p[2].encode("utf-8")) <= 72]
        for uid, username, _ in largas:
            print(f"  AVISO: id={uid} usuario={username} tiene una contraseña de más de 72 bytes; se OMITE "
                  "(debe restablecerse a mano).")

        if not pendientes:
            print("Nada que hacer: no hay contraseñas en texto plano.")
            return 0
        if not args.aplicar:
            print(f"Simulacro: se convertirían {len(convertibles)} y se omitirían {len(largas)}. "
                  "No se modificó nada. Use --aplicar para convertir.")
            return 0
        if not args.si:
            if input(f"Se hashearán {len(convertibles)} contraseñas en '{bd}'. Escriba SI para continuar: ").strip() != "SI":
                print("Cancelado.")
                return 1

        convertidos = 0
        with conn.cursor() as cur:
            for uid, _, plano in convertibles:
                nuevo = bcrypt.hashpw(plano.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                # La condición password = plano evita pisar un cambio concurrente
                cur.execute("UPDATE users SET password = %s WHERE id = %s AND password = %s", (nuevo, uid, plano))
                convertidos += cur.rowcount
        conn.commit()
        cambiados = len(convertibles) - convertidos
        print(f"Listo: {convertidos} contraseñas convertidas a bcrypt; "
              f"{cambiados} omitidas por cambios concurrentes; {len(largas)} omitidas por exceder 72 bytes.")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"Error: {type(e).__name__}. No se aplicó ningún cambio.", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
