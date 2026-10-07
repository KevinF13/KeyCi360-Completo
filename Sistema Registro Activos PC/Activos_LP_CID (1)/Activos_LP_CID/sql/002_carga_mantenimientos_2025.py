"""
Carga del cronograma de mantenimiento preventivo 2025 (equipos PROPIOS asignados).

- Los equipos ARRIENDO/RENTADO no se incluyen: su mantenimiento lo hace el proveedor.
- Los equipos sin persona asignada no se incluyen.
- Los equipos se ordenan por empresa y persona y se reparten en bloques entre los días del cronograma.
- Técnico según la empresa de la persona asignada.
- Cada registro queda con usuario_registro = MARCA para poder revertir la carga completa.

Uso (la conexión sale de DB_* del entorno o del .env):
    python sql/002_carga_mantenimientos_2025.py              -> vista previa + CSV, no escribe
    python sql/002_carga_mantenimientos_2025.py --aplicar    -> inserta en una sola transacción
    python sql/002_carga_mantenimientos_2025.py --revertir   -> borra solo los registros de esta carga
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
load_dotenv(RAIZ / ".env")  # no sobreescribe variables DB_* ya definidas

from activos_equipos import get_conn  # noqa: E402

MARCA = "carga_cronograma_2025"

DIAS = [date(2025, 11, d) for d in (26, 27, 28)] + [
    date(2025, 12, d) for d in (1, 2, 3, 4, 8, 9, 10, 11, 15, 16, 17)
]

TECNICO_POR_EMPRESA = {
    "BLENASTOR": "SUNTAXI MORALES DIEGO FABRICIO",
    "GENA": "SUNTAXI MORALES DIEGO FABRICIO",
    "FARMACID": "VALLE VILLACIS JONATHAN ANDRES",
    "PHARMABRAND": "VALLE VILLACIS JONATHAN ANDRES",
    "CASA LINDA": "TERAN TEJADA SERGIO GEOVANNY",
}
TECNICO_POR_DEFECTO = "VALLE VILLACIS JONATHAN ANDRES"

DESCRIPCION = """1. Limpieza física: desmontaje del gabinete y limpieza de componentes internos (ventiladores, disipadores, placa madre); limpieza de puertos y conectores con aire comprimido; limpieza externa del gabinete y periféricos.
2. Verificación de componentes: fuente de alimentación (conexión y estado); discos duros (salud mediante SMART); memoria RAM (test de memoria); placa madre (inspección visual de daños o conexiones sueltas).
3. Actualización de software: sistema operativo a la última versión; últimas actualizaciones de drivers; revisión y actualización de antivirus y firewall.
4. Pruebas de funcionamiento: pruebas de rendimiento (benchmarking); verificación de conectividad de red y periféricos (teclado, ratón, impresora)."""

CONSULTA_EQUIPOS = """
    WITH ultima_asignacion AS (
        SELECT DISTINCT ON (ca.computer_id) ca.computer_id, ca.person_id
        FROM computer_assignments ca
        WHERE ca.activo = TRUE
        ORDER BY ca.computer_id, ca.fecha_asignacion DESC, ca.id DESC
    )
    SELECT c.id, c.numero_serie, p.nombre, comp.nombre
    FROM computers c
    JOIN statuses s ON s.id = c.estado_id
    JOIN ultima_asignacion ua ON ua.computer_id = c.id
    JOIN people p ON p.id = ua.person_id
    LEFT JOIN companies comp ON comp.id = p.company_id
    WHERE UPPER(c.tipo_propiedad) = 'PROPIO'
      AND s.nombre <> 'ELIMINADO'
    ORDER BY comp.nombre NULLS LAST, p.nombre, c.numero_serie
"""


def repartir(equipos):
    """Bloques contiguos casi iguales: los primeros días reciben el sobrante."""
    base, sobrante = divmod(len(equipos), len(DIAS))
    plan, i = [], 0
    for n, dia in enumerate(DIAS):
        tam = base + (1 if n < sobrante else 0)
        for comp_id, serie, persona, empresa in equipos[i:i + tam]:
            tecnico = TECNICO_POR_EMPRESA.get((empresa or "").strip().upper(), TECNICO_POR_DEFECTO)
            plan.append({"computer_id": comp_id, "serie": serie, "persona": persona,
                         "empresa": empresa or "", "fecha": dia, "tecnico": tecnico})
        i += tam
    return plan


def main():
    ap = argparse.ArgumentParser()
    grupo = ap.add_mutually_exclusive_group()
    grupo.add_argument("--aplicar", action="store_true")
    grupo.add_argument("--revertir", action="store_true")
    args = ap.parse_args()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database(), inet_server_addr(), inet_server_port()")
        print("Base de datos: %s en %s:%s" % cur.fetchone())

        if args.revertir:
            cur.execute("DELETE FROM computer_maintenance WHERE usuario_registro = %s", (MARCA,))
            print(f"Registros eliminados de la carga '{MARCA}': {cur.rowcount}")
            conn.commit()
            return

        cur.execute("SELECT count(*) FROM computer_maintenance WHERE usuario_registro = %s", (MARCA,))
        ya_cargados = cur.fetchone()[0]

        cur.execute(CONSULTA_EQUIPOS)
        plan = repartir(cur.fetchall())

        salida = RAIZ / "sql" / "002_vista_previa_mantenimientos_2025.csv"
        with open(salida, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["fecha", "serie", "persona", "empresa", "tecnico", "computer_id"],
                               delimiter=";")
            w.writeheader()
            w.writerows(plan)

        print(f"Equipos PROPIOS asignados: {len(plan)}  (vista previa: {salida.name})")
        for dia in DIAS:
            n = sum(1 for p in plan if p["fecha"] == dia)
            print(f"  {dia.isoformat()}: {n} equipos")
        for tecnico in sorted({p["tecnico"] for p in plan}):
            print(f"  {tecnico}: {sum(1 for p in plan if p['tecnico'] == tecnico)} equipos")

        if not args.aplicar:
            print("Vista previa: no se escribió nada. Use --aplicar para insertar.")
            return

        if ya_cargados:
            sys.exit(f"ABORTADO: ya existen {ya_cargados} registros de '{MARCA}'. Use --revertir antes de recargar.")

        cur.executemany("""
            INSERT INTO computer_maintenance
            (computer_id, fecha_mantenimiento, tipo_mantenimiento, descripcion, tecnico, costo, usuario_registro)
            VALUES (%s, %s, 'PREVENTIVO', %s, %s, NULL, %s)
        """, [(p["computer_id"], p["fecha"], DESCRIPCION, p["tecnico"], MARCA) for p in plan])

        cur.execute("SELECT count(*) FROM computer_maintenance WHERE usuario_registro = %s", (MARCA,))
        insertados = cur.fetchone()[0]
        if insertados != len(plan):
            conn.rollback()
            sys.exit(f"ABORTADO: se esperaban {len(plan)} registros y hay {insertados}. No se guardó nada.")
        conn.commit()
        print(f"Insertados {insertados} mantenimientos.")


if __name__ == "__main__":
    main()
