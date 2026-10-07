from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor
from datetime import date
import logging

from auth import lectura_usuario_escritura_admin, usuario_actual

from activos_equipos import get_conn, _texto_requerido, _entero_requerido


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mantenimiento", tags=["Mantenimiento"], dependencies=[Depends(lectura_usuario_escritura_admin)])

TIPOS_MANTENIMIENTO = {"PREVENTIVO", "CORRECTIVO"}


def _validar_mantenimiento(data: dict) -> dict:
    tipo = _texto_requerido(data, "tipo_mantenimiento").upper()
    if tipo not in TIPOS_MANTENIMIENTO:
        raise HTTPException(status_code=400, detail="El tipo de mantenimiento debe ser PREVENTIVO o CORRECTIVO.")

    fecha = data.get("fecha_mantenimiento") or date.today().isoformat()
    try:
        fecha = date.fromisoformat(str(fecha)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="La fecha de mantenimiento no es valida.")
    if fecha > date.today():
        raise HTTPException(status_code=400, detail="La fecha de mantenimiento no puede ser futura.")

    costo = data.get("costo")
    if costo in (None, ""):
        costo = None
    else:
        try:
            costo = float(costo)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="El costo debe ser un numero valido.")
        if costo < 0:
            raise HTTPException(status_code=400, detail="El costo no puede ser negativo.")

    return {
        "tipo": tipo,
        "fecha": fecha,
        "descripcion": _texto_requerido(data, "descripcion"),
        "tecnico": (str(data.get("tecnico") or "").strip().upper()) or None,
        "costo": costo,
    }


# Ultima asignacion activa de cada equipo (persona que lo tiene hoy)
_CTE_ULTIMA_ASIGNACION = """
    WITH ultima_asignacion AS (
        SELECT DISTINCT ON (ca.computer_id)
            ca.computer_id,
            ca.person_id,
            ca.fecha_asignacion
        FROM computer_assignments ca
        WHERE ca.activo = TRUE
        ORDER BY ca.computer_id, ca.fecha_asignacion DESC, ca.id DESC
    )
"""

# Datos completos del equipo, su persona asignada y su empresa (alias c, hs, s, ua, p, comp)
_COLUMNAS_EQUIPO = """
    c.numero_serie,
    hs.tipo_equipo,
    hs.marca,
    hs.modelo,
    hs.procesador,
    hs.ram_gb,
    hs.almacenamiento,
    hs.sistema_operativo,
    hs.pantalla,
    hs.otros,
    c.tipo_propiedad,
    c.tarifa_mensual,
    c.anio_fabricacion,
    c.fecha_recepcion_proveedor,
    c.observaciones,
    s.nombre AS estado,
    p.nombre AS usuario_actual,
    p.cedula,
    p.cargo,
    p.area,
    p.email,
    ua.fecha_asignacion AS fecha_entrega,
    comp.nombre AS company_nombre
"""

_JOINS_EQUIPO = """
    JOIN hardware_specs hs ON c.hardware_spec_id = hs.id
    JOIN statuses s ON c.estado_id = s.id
    LEFT JOIN ultima_asignacion ua ON ua.computer_id = c.id
    LEFT JOIN people p ON p.id = ua.person_id
    LEFT JOIN companies comp ON comp.id = p.company_id
"""


# =========================
# CONSULTAS
# =========================
@router.get("/computadoras")
def get_computadoras_mantenimiento():
    logger.debug("GET /mantenimiento/computadoras")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute(_CTE_ULTIMA_ASIGNACION + """
                SELECT
                    c.id,
                """ + _COLUMNAS_EQUIPO + """,
                    m.primer_mantenimiento,
                    m.ultimo_mantenimiento,
                    COALESCE(m.total_mantenimientos, 0) AS total_mantenimientos
                FROM computers c
                """ + _JOINS_EQUIPO + """
                LEFT JOIN (
                    SELECT computer_id,
                           MIN(fecha_mantenimiento) AS primer_mantenimiento,
                           MAX(fecha_mantenimiento) AS ultimo_mantenimiento,
                           COUNT(*) AS total_mantenimientos
                    FROM computer_maintenance
                    GROUP BY computer_id
                ) m ON m.computer_id = c.id
                WHERE s.nombre <> 'ELIMINADO'
                ORDER BY c.numero_serie
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /mantenimiento/computadoras")
            raise HTTPException(status_code=500, detail="Error al consultar computadoras.")


@router.get("")
def get_mantenimientos():
    logger.debug("GET /mantenimiento")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute(_CTE_ULTIMA_ASIGNACION + """
                SELECT cm.id, cm.computer_id, cm.fecha_mantenimiento, cm.tipo_mantenimiento,
                       cm.descripcion, cm.tecnico, cm.costo, cm.usuario_registro, cm.created_at,
                """ + _COLUMNAS_EQUIPO + """
                FROM computer_maintenance cm
                JOIN computers c ON c.id = cm.computer_id
                """ + _JOINS_EQUIPO + """
                ORDER BY cm.fecha_mantenimiento DESC, cm.id DESC
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /mantenimiento")
            raise HTTPException(status_code=500, detail="Error al consultar mantenimientos.")


@router.get("/computadoras/{computer_id}")
def get_mantenimientos_computadora(computer_id: int):
    logger.debug(f"GET /mantenimiento/computadoras/{computer_id}")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT id, computer_id, fecha_mantenimiento, tipo_mantenimiento,
                       descripcion, tecnico, costo, usuario_registro, created_at
                FROM computer_maintenance
                WHERE computer_id = %s
                ORDER BY fecha_mantenimiento DESC, id DESC
            """, (computer_id,))
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /mantenimiento/computadoras/{computer_id}")
            raise HTTPException(status_code=500, detail="Error al consultar mantenimientos.")


# =========================
# CREACION / ELIMINACION
# =========================
@router.post("")
def create_mantenimiento(data: dict, usuario: dict = Depends(usuario_actual)):
    logger.debug("POST /mantenimiento")
    computer_id = _entero_requerido(data, "computer_id")
    m = _validar_mantenimiento(data)
    # La autoría la fija el servidor: el campo usuario_registro del cuerpo (si llega) se ignora
    usuario_registro = usuario["username"]

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                SELECT c.id
                FROM computers c
                JOIN statuses s ON c.estado_id = s.id
                WHERE c.id = %s
                  AND s.nombre <> 'ELIMINADO'
            """, (computer_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="La computadora no existe o esta eliminada.")

            cur.execute("""
                INSERT INTO computer_maintenance
                (computer_id, fecha_mantenimiento, tipo_mantenimiento,
                 descripcion, tecnico, costo, usuario_registro)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (computer_id, m["fecha"], m["tipo"], m["descripcion"], m["tecnico"], m["costo"], usuario_registro))
            maintenance_id = cur.fetchone()[0]
            conn.commit()

            return {
                "maintenance_id": maintenance_id,
                "message": "Mantenimiento registrado correctamente."
            }

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en POST /mantenimiento")
            raise HTTPException(status_code=500, detail="Error al registrar mantenimiento.")


@router.put("/{id}")
def update_mantenimiento(id: int, data: dict):
    logger.debug(f"PUT /mantenimiento/{id}")
    m = _validar_mantenimiento(data)

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                UPDATE computer_maintenance
                SET fecha_mantenimiento = %s,
                    tipo_mantenimiento = %s,
                    descripcion = %s,
                    tecnico = %s,
                    costo = %s
                WHERE id = %s
            """, (m["fecha"], m["tipo"], m["descripcion"], m["tecnico"], m["costo"], id))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Mantenimiento no encontrado")
            conn.commit()
            return {"message": "Mantenimiento actualizado correctamente."}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en PUT /mantenimiento/{id}")
            raise HTTPException(status_code=500, detail="Error al actualizar mantenimiento.")


@router.delete("/{id}")
def delete_mantenimiento(id: int):
    logger.debug(f"DELETE /mantenimiento/{id}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("DELETE FROM computer_maintenance WHERE id = %s", (id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Mantenimiento no encontrado")
            conn.commit()
            return {"message": "Mantenimiento eliminado"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en DELETE /mantenimiento/{id}")
            raise HTTPException(status_code=500, detail="Error al eliminar mantenimiento.")
