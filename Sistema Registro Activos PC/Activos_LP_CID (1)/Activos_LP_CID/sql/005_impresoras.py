"""
Módulo de impresoras: crea las tablas printers y printer_readings y rellena printers a partir de las
computadoras de tipo impresora (hardware_specs.tipo_equipo ILIKE 'impres%').

Idempotente: CREATE ... IF NOT EXISTS y solo se insertan impresoras que aún no tienen fila en printers.
Reversible: solo agrega objetos nuevos (no toca computers ni hardware_specs). Para revertir:
    DROP TABLE printer_readings; DROP TABLE printers;   (se pierden las lecturas cargadas)
Por defecto es un simulacro (dry-run): no modifica nada y solo informa qué haría.

es_color se infiere por heurística sobre el modelo: " C" (o "-C") seguido de un dígito (p. ej. "iR-ADV C5550",
"ADV-C5550") o la palabra "COLOR". El script lista las impresoras inferidas a color para revisarlas.
company_id queda NULL.

Uso (desde la carpeta del backend, con las variables DB_* del .env o del entorno):
    python sql/005_impresoras.py                 -> simulacro
    python sql/005_impresoras.py --aplicar       -> pide confirmación y aplica
    python sql/005_impresoras.py --aplicar --si  -> aplica sin preguntar
"""
import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

DDL = """
CREATE TABLE IF NOT EXISTS printers (
  id            SERIAL PRIMARY KEY,
  computer_id   INTEGER NOT NULL UNIQUE REFERENCES computers(id),
  company_id    INTEGER NULL REFERENCES companies(id),
  ip_address    VARCHAR(45) NULL,
  hostname      VARCHAR(100) NULL,
  area          VARCHAR(100) NULL,
  ubicacion     VARCHAR(150) NULL,
  es_color      BOOLEAN NOT NULL DEFAULT FALSE,
  proveedor     VARCHAR(100) NULL,
  observaciones TEXT NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT now(),
  updated_at    TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_printers_ip ON printers(ip_address) WHERE ip_address IS NOT NULL;

CREATE TABLE IF NOT EXISTS printer_readings (
  id             SERIAL PRIMARY KEY,
  printer_id     INTEGER NOT NULL REFERENCES printers(id) ON DELETE CASCADE,
  periodo        DATE NOT NULL,
  fecha_lectura  DATE NOT NULL,
  contador_bn    BIGINT NOT NULL CHECK (contador_bn >= 0),
  contador_color BIGINT NOT NULL DEFAULT 0 CHECK (contador_color >= 0),
  es_reinicio    BOOLEAN NOT NULL DEFAULT FALSE,
  observaciones  TEXT NULL,
  registrado_por VARCHAR(50) NOT NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT now(),
  UNIQUE (printer_id, periodo),
  CHECK (periodo = date_trunc('month', periodo)::date)
);
CREATE INDEX IF NOT EXISTS ix_printer_readings_periodo ON printer_readings(periodo);
"""


def inferir_color(modelo: str) -> bool:
    modelo = modelo or ""
    return bool(re.search(r"(?:^|[\s-])C\d", modelo) or "COLOR" in modelo.upper())


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
            cur.execute("SELECT to_regclass('printers') IS NOT NULL, to_regclass('printer_readings') IS NOT NULL")
            existe_printers, existe_lecturas = cur.fetchone()
            print(f"BD: {bd} ({addr or 'socket local'})  printers existe: {existe_printers}  "
                  f"printer_readings existe: {existe_lecturas}")

            filtro = "AND NOT EXISTS (SELECT 1 FROM printers p WHERE p.computer_id = c.id)" if existe_printers else ""
            cur.execute(f"""
                SELECT c.id, c.numero_serie, hs.modelo
                FROM computers c
                JOIN hardware_specs hs ON hs.id = c.hardware_spec_id
                WHERE hs.tipo_equipo ILIKE 'impres%%'
                  {filtro}
                ORDER BY c.id
            """)
            pendientes = cur.fetchall()

        a_color = [(cid, serie, (modelo or "").strip()) for cid, serie, modelo in pendientes if inferir_color(modelo)]
        print(f"Impresoras por rellenar: {len(pendientes)}; inferidas a color: {len(a_color)}")
        for cid, serie, modelo in a_color:
            print(f"  - color: computer_id={cid} serie={serie} modelo={modelo}")

        if not args.aplicar:
            print("Simulacro: no se modificó nada. Use --aplicar para aplicar.")
            return 0
        if not args.si:
            if input(f"Se aplicará la migración 005 en '{bd}'. Escriba SI para continuar: ").strip() != "SI":
                print("Cancelado.")
                return 1

        insertadas = 0
        with conn.cursor() as cur:
            cur.execute(DDL)
            # Se vuelve a leer ya con la tabla creada (cubre la primera ejecución y las siguientes)
            cur.execute("""
                SELECT c.id, hs.modelo
                FROM computers c
                JOIN hardware_specs hs ON hs.id = c.hardware_spec_id
                WHERE hs.tipo_equipo ILIKE 'impres%%'
                  AND NOT EXISTS (SELECT 1 FROM printers p WHERE p.computer_id = c.id)
                ORDER BY c.id
            """)
            for cid, modelo in cur.fetchall():
                cur.execute(
                    "INSERT INTO printers (computer_id, es_color) VALUES (%s, %s) ON CONFLICT (computer_id) DO NOTHING",
                    (cid, inferir_color(modelo)),
                )
                insertadas += cur.rowcount
        conn.commit()
        print(f"Listo: tablas verificadas; {insertadas} impresoras insertadas en printers.")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"Error: {type(e).__name__}: {e}. No se aplicó ningún cambio.", file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
