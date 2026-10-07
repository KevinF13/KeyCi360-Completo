"""Módulo de impresoras: inventario (printers sobre computers) y lecturas mensuales de contadores acumulados.

El consumo de una lectura es el contador menos el de la lectura anterior de la misma impresora (por periodo);
se calcula al leer (LAG), no se almacena."""
import logging
from datetime import date

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg2.extras import RealDictCursor

from auth import lectura_usuario_escritura_admin, usuario_actual
from db import get_conn
from schemas import PrinterIn, PrinterUpdate, ReadingBatchIn, ReadingIn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/impresoras", tags=["Impresoras"], dependencies=[Depends(lectura_usuario_escritura_admin)])

_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
_TIPO_EQUIPO = "Impresora"
_SPEC_SIN_DATOS = ("N/A", 0, "N/A", "N/A")  # procesador, ram_gb, almacenamiento, sistema_operativo


class _ErrorLectura(Exception):
    """Regla de negocio incumplida al validar una lectura (el lote la reporta por fila)."""

    def __init__(self, status: int, mensaje: str):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje


# ---------- utilidades ----------
def _mes_texto(d: date) -> str:
    return f"{_MESES[d.month - 1]} de {d.year}"


def _periodo_a_fecha(periodo: str) -> date:
    return date(int(periodo[:4]), int(periodo[5:7]), 1)


def _periodo_texto(d: date) -> str:
    return d.strftime("%Y-%m")


def _consumo_sql(contador: str, anterior: str) -> str:
    return (f"CASE WHEN es_reinicio THEN {contador} WHEN {anterior} IS NULL THEN NULL "
            f"ELSE {contador} - {anterior} END")


# Lecturas de una impresora con su consumo (LAG sobre todo el histórico de esa impresora)
_SQL_LECTURAS = f"""
    SELECT x.id, x.printer_id, x.periodo, x.fecha_lectura, x.contador_bn, x.contador_color, x.es_reinicio,
           x.observaciones, x.registrado_por, x.created_at,
           {_consumo_sql('x.contador_bn', 'x.prev_bn')} AS consumo_bn,
           {_consumo_sql('x.contador_color', 'x.prev_color')} AS consumo_color
    FROM (
        SELECT r.*, LAG(r.contador_bn) OVER w AS prev_bn, LAG(r.contador_color) OVER w AS prev_color
        FROM printer_readings r
        WHERE r.printer_id = %s
        WINDOW w AS (ORDER BY r.periodo)
    ) x
"""


def _lectura_json(f: dict) -> dict:
    return {
        "id": f["id"], "printer_id": f["printer_id"], "periodo": _periodo_texto(f["periodo"]),
        "fecha_lectura": f["fecha_lectura"].isoformat(), "contador_bn": f["contador_bn"],
        "contador_color": f["contador_color"], "es_reinicio": f["es_reinicio"],
        "consumo_bn": f["consumo_bn"], "consumo_color": f["consumo_color"],
        "observaciones": f["observaciones"], "registrado_por": f["registrado_por"],
        "created_at": f["created_at"].isoformat(),
    }


def _lecturas_de(cur, printer_id: int) -> list:
    cur.execute(_SQL_LECTURAS + " ORDER BY x.periodo DESC", (printer_id,))
    return [_lectura_json(f) for f in cur.fetchall()]


def _lectura_por_id(cur, lectura_id: int) -> dict:
    cur.execute("SELECT printer_id FROM printer_readings WHERE id = %s", (lectura_id,))
    fila = cur.fetchone()
    if not fila:
        raise HTTPException(status_code=404, detail="Lectura no encontrada")
    cur.execute(_SQL_LECTURAS + " WHERE x.id = %s", (fila["printer_id"], lectura_id))
    return _lectura_json(cur.fetchone())


_SQL_IMPRESORAS = f"""
    SELECT p.id, p.computer_id, c.numero_serie, hs.marca, hs.modelo, c.tipo_propiedad, c.tarifa_mensual,
           s.nombre AS estado, p.company_id, co.nombre AS empresa, p.ip_address, p.hostname, p.area,
           p.ubicacion, p.es_color, p.proveedor, p.observaciones,
           l.id AS l_id, l.periodo AS l_periodo, l.fecha_lectura AS l_fecha, l.contador_bn AS l_bn,
           l.contador_color AS l_color, l.consumo_bn AS l_cbn, l.consumo_color AS l_ccolor,
           EXISTS (SELECT 1 FROM printer_readings m WHERE m.printer_id = p.id AND m.periodo = %(mes)s)
               AS lectura_mes_actual
    FROM printers p
    JOIN computers c ON c.id = p.computer_id
    JOIN hardware_specs hs ON hs.id = c.hardware_spec_id
    LEFT JOIN statuses s ON s.id = c.estado_id
    LEFT JOIN companies co ON co.id = p.company_id
    LEFT JOIN LATERAL (
        SELECT y.id, y.periodo, y.fecha_lectura, y.contador_bn, y.contador_color,
               {_consumo_sql('y.contador_bn', 'y.prev_bn')} AS consumo_bn,
               {_consumo_sql('y.contador_color', 'y.prev_color')} AS consumo_color
        FROM (
            SELECT r.*, LAG(r.contador_bn) OVER w AS prev_bn, LAG(r.contador_color) OVER w AS prev_color
            FROM printer_readings r
            WHERE r.printer_id = p.id
            WINDOW w AS (ORDER BY r.periodo)
        ) y
        ORDER BY y.periodo DESC
        LIMIT 1
    ) l ON TRUE
"""


def _impresora_json(f: dict) -> dict:
    ultima = consumo = None
    if f["l_id"] is not None:
        per = _periodo_texto(f["l_periodo"])
        ultima = {"id": f["l_id"], "periodo": per, "fecha_lectura": f["l_fecha"].isoformat(),
                  "contador_bn": f["l_bn"], "contador_color": f["l_color"]}
        consumo = {"periodo": per, "bn": f["l_cbn"], "color": f["l_ccolor"]}
    return {
        "id": f["id"], "computer_id": f["computer_id"], "numero_serie": f["numero_serie"], "marca": f["marca"],
        "modelo": f["modelo"], "tipo_propiedad": f["tipo_propiedad"],
        "tarifa_mensual": float(f["tarifa_mensual"]) if f["tarifa_mensual"] is not None else None,
        "estado": f["estado"], "company_id": f["company_id"], "empresa": f["empresa"],
        "ip_address": f["ip_address"], "hostname": f["hostname"], "area": f["area"],
        "ubicacion": f["ubicacion"], "es_color": f["es_color"], "proveedor": f["proveedor"],
        "observaciones": f["observaciones"], "ultima_lectura": ultima, "consumo_ultimo": consumo,
        "lectura_mes_actual": f["lectura_mes_actual"],
    }


def _impresora_por_id(cur, printer_id: int) -> dict:
    cur.execute(_SQL_IMPRESORAS + " WHERE p.id = %(id)s AND COALESCE(s.nombre, '') <> 'ELIMINADO'",
                {"mes": date.today().replace(day=1), "id": printer_id})
    fila = cur.fetchone()
    if not fila:
        raise HTTPException(status_code=404, detail="Impresora no encontrada")
    return _impresora_json(fila)


def _bloquear_impresora(cur, printer_id: int) -> dict:
    """Bloquea la fila de la impresora: serializa las altas/ediciones de lecturas de esa impresora."""
    cur.execute("SELECT id, es_color FROM printers WHERE id = %s FOR UPDATE", (printer_id,))
    fila = cur.fetchone()
    if not fila:
        raise HTTPException(status_code=404, detail="Impresora no encontrada")
    return fila


# ---------- validación de lecturas ----------
def _validar_lectura(cur, printer: dict, periodo: date, fecha: date, bn: int, color: int,
                     reinicio: bool, excluir_id=None) -> None:
    """Lanza _ErrorLectura si la lectura incumple las reglas de negocio. Debe llamarse con la impresora bloqueada."""
    hoy = date.today()
    if periodo > hoy.replace(day=1):
        raise _ErrorLectura(400, "El periodo no puede ser futuro.")
    if fecha > hoy:
        raise _ErrorLectura(400, "La fecha de lectura no puede ser futura.")
    if not printer["es_color"] and color > 0:
        raise _ErrorLectura(400, "La impresora es monocromática: el contador de color debe ser 0.")

    excl = excluir_id if excluir_id is not None else -1
    cur.execute("SELECT 1 FROM printer_readings WHERE printer_id = %s AND periodo = %s AND id <> %s",
                (printer["id"], periodo, excl))
    if cur.fetchone():
        raise _ErrorLectura(409, f"Ya existe una lectura de {_mes_texto(periodo)} para esta impresora.")

    cur.execute("""SELECT periodo, contador_bn, contador_color FROM printer_readings
                   WHERE printer_id = %s AND periodo < %s AND id <> %s ORDER BY periodo DESC LIMIT 1""",
                (printer["id"], periodo, excl))
    anterior = cur.fetchone()
    cur.execute("""SELECT periodo, contador_bn, contador_color, es_reinicio FROM printer_readings
                   WHERE printer_id = %s AND periodo > %s AND id <> %s ORDER BY periodo ASC LIMIT 1""",
                (printer["id"], periodo, excl))
    siguiente = cur.fetchone()

    if anterior and not reinicio:
        for nombre, valor, previo in (("B/N", bn, anterior["contador_bn"]),
                                      ("de color", color, anterior["contador_color"])):
            if valor < previo:
                raise _ErrorLectura(400, (
                    f"El contador {nombre} ({valor}) es menor que la lectura anterior ({previo}) del "
                    f"{_mes_texto(anterior['periodo'])}. Si cambió el equipo o se reinició el contador, "
                    "marca 'Reinicio de contador'."))
    if siguiente and not siguiente["es_reinicio"]:
        for nombre, valor, posterior in (("B/N", bn, siguiente["contador_bn"]),
                                         ("de color", color, siguiente["contador_color"])):
            if valor > posterior:
                raise _ErrorLectura(400, (
                    f"El contador {nombre} ({valor}) es mayor que la lectura siguiente ({posterior}) del "
                    f"{_mes_texto(siguiente['periodo'])}."))


def _http(e: _ErrorLectura) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.mensaje)


def _validar_hueco(cur, printer_id: int, periodo: date, lectura_id: int, accion: str) -> None:
    """Al quitar la lectura `lectura_id` de `periodo`, la siguiente (si no es reinicio) no puede quedar con un
    contador menor que la anterior. Lanza HTTPException 409. Debe llamarse con la impresora bloqueada."""
    cur.execute("""
        SELECT periodo, contador_bn, contador_color, es_reinicio FROM printer_readings
        WHERE printer_id = %s AND periodo > %s AND id <> %s ORDER BY periodo ASC LIMIT 1
    """, (printer_id, periodo, lectura_id))
    siguiente = cur.fetchone()
    cur.execute("""
        SELECT periodo, contador_bn, contador_color FROM printer_readings
        WHERE printer_id = %s AND periodo < %s AND id <> %s ORDER BY periodo DESC LIMIT 1
    """, (printer_id, periodo, lectura_id))
    anterior = cur.fetchone()
    if (siguiente and anterior and not siguiente["es_reinicio"]
            and (siguiente["contador_bn"] < anterior["contador_bn"]
                 or siguiente["contador_color"] < anterior["contador_color"])):
        raise HTTPException(status_code=409, detail=(
            f"No se puede {accion}: la lectura de {_mes_texto(siguiente['periodo'])} quedaría con un "
            f"contador menor que la de {_mes_texto(anterior['periodo'])}. Corrija o elimine esa lectura primero."))


def _insertar_lectura(cur, printer_id: int, periodo: date, d, usuario: dict) -> int:
    cur.execute("""
        INSERT INTO printer_readings
        (printer_id, periodo, fecha_lectura, contador_bn, contador_color, es_reinicio, observaciones, registrado_por)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (printer_id, periodo, d.fecha_lectura, d.contador_bn, d.contador_color, d.es_reinicio,
          d.observaciones, usuario["username"]))
    return cur.fetchone()["id"]


# ---------- resumen (antes de /{id} para que la ruta fija tenga prioridad) ----------
@router.get("/resumen")
def resumen(meses: int = Query(default=12, ge=1, le=60)):
    hoy = date.today()
    actual = hoy.replace(day=1)
    anterior = date(actual.year - (actual.month == 1), 12 if actual.month == 1 else actual.month - 1, 1)
    inicio_total = actual.year * 12 + actual.month - 1 - (meses - 1)
    inicio = date(inicio_total // 12, inicio_total % 12 + 1, 1)
    def _cons(excluidos: str) -> str:
        # El LAG se calcula por impresora; filtrar impresoras enteras por estado no altera el consumo de las demás.
        return f"""
            SELECT r.printer_id, r.periodo,
                   {_consumo_sql('r.contador_bn', 'LAG(r.contador_bn) OVER w')} AS bn,
                   {_consumo_sql('r.contador_color', 'LAG(r.contador_color) OVER w')} AS color
            FROM printer_readings r
            JOIN printers pf ON pf.id = r.printer_id
            JOIN computers cf ON cf.id = pf.computer_id
            LEFT JOIN statuses sf ON sf.id = cf.estado_id
            WHERE COALESCE(sf.nombre, '') NOT IN {excluidos}
            WINDOW w AS (PARTITION BY r.printer_id ORDER BY r.periodo)
        """
    # serie y consumos del mes: incluyen BAJA (ese consumo ocurrió) y excluyen ELIMINADO; el top solo activas
    cons = _cons("('ELIMINADO')")
    cons_activas = _cons("('ELIMINADO', 'BAJA')")
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT COUNT(*) FILTER (WHERE COALESCE(s.nombre, '') <> 'ELIMINADO') AS total,
                       COUNT(*) FILTER (WHERE COALESCE(s.nombre, '') NOT IN ('ELIMINADO', 'BAJA')) AS activas,
                       COUNT(*) FILTER (WHERE COALESCE(s.nombre, '') NOT IN ('ELIMINADO', 'BAJA') AND p.es_color) AS color,
                       COUNT(*) FILTER (WHERE COALESCE(s.nombre, '') NOT IN ('ELIMINADO', 'BAJA') AND NOT p.es_color) AS monocromo,
                       COUNT(*) FILTER (WHERE COALESCE(s.nombre, '') NOT IN ('ELIMINADO', 'BAJA') AND NOT EXISTS (
                           SELECT 1 FROM printer_readings m WHERE m.printer_id = p.id AND m.periodo = %s)) AS sin_lectura
                FROM printers p
                JOIN computers c ON c.id = p.computer_id
                LEFT JOIN statuses s ON s.id = c.estado_id
            """, (actual,))
            conteos = cur.fetchone()

            cur.execute(f"""
                SELECT m::date AS periodo, COALESCE(SUM(k.bn), 0)::bigint AS bn, COALESCE(SUM(k.color), 0)::bigint AS color
                FROM generate_series(%s::date, %s::date, interval '1 month') m
                LEFT JOIN ({cons}) k ON k.periodo = m::date
                GROUP BY m ORDER BY m
            """, (inicio, actual))
            serie = [{"periodo": _periodo_texto(f["periodo"]), "bn": f["bn"], "color": f["color"]}
                     for f in cur.fetchall()]

            cur.execute(f"""
                SELECT k.periodo, COALESCE(SUM(k.bn), 0)::bigint AS bn, COALESCE(SUM(k.color), 0)::bigint AS color
                FROM ({cons}) k WHERE k.periodo IN (%s, %s) GROUP BY k.periodo
            """, (actual, anterior))
            por_mes = {f["periodo"]: f for f in cur.fetchall()}

            def _mes(d):
                f = por_mes.get(d)
                return {"bn": f["bn"] if f else 0, "color": f["color"] if f else 0}

            cur.execute(f"""
                WITH k AS ({cons_activas}),
                     ultimo AS (SELECT MAX(periodo) AS periodo FROM k WHERE bn IS NOT NULL)
                SELECT p.id AS printer_id, hs.modelo, p.hostname, p.area, co.nombre AS empresa,
                       k.bn::bigint AS bn, COALESCE(k.color, 0)::bigint AS color,
                       (k.bn + COALESCE(k.color, 0))::bigint AS total
                FROM k
                JOIN ultimo u ON u.periodo = k.periodo
                JOIN printers p ON p.id = k.printer_id
                JOIN computers c ON c.id = p.computer_id
                JOIN hardware_specs hs ON hs.id = c.hardware_spec_id
                LEFT JOIN companies co ON co.id = p.company_id
                WHERE k.bn IS NOT NULL
                ORDER BY total DESC, p.id
                LIMIT 5
            """)
            top = [{**f, "modelo": (f["modelo"] or "").strip()} for f in cur.fetchall()]

        return {
            "total": conteos["total"], "activas": conteos["activas"], "color": conteos["color"],
            "monocromo": conteos["monocromo"], "sin_lectura_mes_actual": conteos["sin_lectura"],
            "periodo_actual": _periodo_texto(actual),
            "consumo_mes": _mes(actual), "consumo_mes_anterior": _mes(anterior),
            "serie": serie, "top": top,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error en GET /impresoras/resumen")
        raise HTTPException(status_code=500, detail="Error al obtener el resumen de impresoras.")


# ---------- lote de lecturas (antes de /{id}) ----------
@router.post("/lecturas/lote")
def lote_lecturas(payload: ReadingBatchIn, usuario: dict = Depends(usuario_actual)):
    """Atómico: con un solo error no se inserta nada. modo='validar' nunca escribe.
    `indice` es la posición (desde 0) de la lectura dentro de `lecturas`."""
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            ids = sorted({i.printer_id for i in payload.lecturas})
            cur.execute("SELECT id, es_color FROM printers WHERE id = ANY(%s) ORDER BY id FOR UPDATE", (ids,))
            impresoras = {f["id"]: f for f in cur.fetchall()}

            errores, validas = [], 0
            for indice, item in enumerate(payload.lecturas):
                periodo = _periodo_a_fecha(item.periodo)
                impresora = impresoras.get(item.printer_id)
                try:
                    if impresora is None:
                        raise _ErrorLectura(404, "La impresora no existe.")
                    _validar_lectura(cur, impresora, periodo, item.fecha_lectura, item.contador_bn,
                                     item.contador_color, item.es_reinicio)
                    # Se inserta en la transacción para que las filas siguientes del lote vean a las anteriores
                    _insertar_lectura(cur, item.printer_id, periodo, item, usuario)
                    validas += 1
                except _ErrorLectura as e:
                    errores.append({"indice": indice, "printer_id": item.printer_id,
                                    "periodo": item.periodo, "mensaje": e.mensaje})

            aplicar = payload.modo == "aplicar" and not errores
            if not aplicar:
                conn.rollback()
            # creadas: lecturas realmente escritas (0 en 'validar' o si el lote se rechaza);
            # validas: lecturas que pasaron la validación, para informar en 'validar'
            return {"ok": not errores, "creadas": validas if aplicar else 0,
                    "validas": validas, "errores": errores}
    except Exception:
        logger.exception("Error en POST /impresoras/lecturas/lote")
        raise HTTPException(status_code=500, detail="Error al procesar el lote de lecturas.")


# ---------- lecturas por id ----------
@router.put("/lecturas/{lectura_id}")
def actualizar_lectura(lectura_id: int, payload: ReadingIn):
    periodo = _periodo_a_fecha(payload.periodo)
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT printer_id FROM printer_readings WHERE id = %s", (lectura_id,))
            fila = cur.fetchone()
            if not fila:
                raise HTTPException(status_code=404, detail="Lectura no encontrada")
            impresora = _bloquear_impresora(cur, fila["printer_id"])
            cur.execute("SELECT periodo FROM printer_readings WHERE id = %s FOR UPDATE", (lectura_id,))
            actual = cur.fetchone()
            if not actual:
                raise HTTPException(status_code=404, detail="Lectura no encontrada")
            if actual["periodo"] != periodo:  # al salir de su posición antigua no puede romper a los vecinos
                _validar_hueco(cur, fila["printer_id"], actual["periodo"], lectura_id, "mover la lectura")
            try:
                _validar_lectura(cur, impresora, periodo, payload.fecha_lectura, payload.contador_bn,
                                 payload.contador_color, payload.es_reinicio, excluir_id=lectura_id)
            except _ErrorLectura as e:
                raise _http(e)
            cur.execute("""
                UPDATE printer_readings
                SET periodo = %s, fecha_lectura = %s, contador_bn = %s, contador_color = %s,
                    es_reinicio = %s, observaciones = %s
                WHERE id = %s
            """, (periodo, payload.fecha_lectura, payload.contador_bn, payload.contador_color,
                  payload.es_reinicio, payload.observaciones, lectura_id))
            return _lectura_por_id(cur, lectura_id)
    except HTTPException:
        raise
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"Ya existe una lectura de {_mes_texto(periodo)} para esta impresora.")
    except Exception:
        logger.exception("Error en PUT /impresoras/lecturas/{id}")
        raise HTTPException(status_code=500, detail="Error al actualizar la lectura.")


@router.delete("/lecturas/{lectura_id}", status_code=204)
def eliminar_lectura(lectura_id: int):
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Orden uniforme de bloqueos: impresora -> lectura. El periodo se lee tras bloquear
            # (un PUT concurrente pudo cambiarlo) y la lectura puede haber desaparecido.
            cur.execute("SELECT printer_id FROM printer_readings WHERE id = %s", (lectura_id,))
            previa = cur.fetchone()
            if not previa:
                raise HTTPException(status_code=404, detail="Lectura no encontrada")
            _bloquear_impresora(cur, previa["printer_id"])
            cur.execute("SELECT printer_id, periodo FROM printer_readings WHERE id = %s FOR UPDATE", (lectura_id,))
            fila = cur.fetchone()
            if not fila:
                raise HTTPException(status_code=404, detail="Lectura no encontrada")
            _validar_hueco(cur, fila["printer_id"], fila["periodo"], lectura_id, "eliminar")
            cur.execute("DELETE FROM printer_readings WHERE id = %s", (lectura_id,))
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error en DELETE /impresoras/lecturas/{id}")
        raise HTTPException(status_code=500, detail="Error al eliminar la lectura.")


# ---------- impresoras ----------
@router.get("")
def listar_impresoras(incluir_baja: bool = False):
    excluidos = "('ELIMINADO')" if incluir_baja else "('ELIMINADO', 'BAJA')"
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_SQL_IMPRESORAS + f" WHERE COALESCE(s.nombre, '') NOT IN {excluidos} ORDER BY p.id",
                        {"mes": date.today().replace(day=1)})
            return [_impresora_json(f) for f in cur.fetchall()]
    except Exception:
        logger.exception("Error en GET /impresoras")
        raise HTTPException(status_code=500, detail="Error al obtener impresoras.")


@router.get("/{printer_id}")
def obtener_impresora(printer_id: int):
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            return _impresora_por_id(cur, printer_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error en GET /impresoras/{id}")
        raise HTTPException(status_code=500, detail="Error al obtener la impresora.")


def _validar_compania_e_ip(cur, company_id, ip, excluir_printer_id=None):
    if company_id is not None:
        cur.execute("SELECT 1 FROM companies WHERE id = %s", (company_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail="La compañía indicada no existe.")
    if ip is not None:
        cur.execute("SELECT 1 FROM printers WHERE ip_address = %s AND id <> %s", (ip, excluir_printer_id or -1))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="La dirección IP ya está asignada a otra impresora.")


def _spec_para(cur, marca: str, modelo: str, base: tuple = _SPEC_SIN_DATOS, extra=(None, None, 5)) -> int:
    """Devuelve el id de la especificación idéntica (reactivándola si estaba eliminada) o la crea."""
    clave = (_TIPO_EQUIPO, marca, modelo) + tuple(base)
    cur.execute("""
        SELECT id, status_id FROM hardware_specs
        WHERE tipo_equipo = %s AND marca = %s AND modelo = %s AND procesador = %s
          AND ram_gb = %s AND almacenamiento = %s AND sistema_operativo = %s
    """, clave)
    existente = cur.fetchone()
    if existente:
        if existente["status_id"] == 7:
            cur.execute("UPDATE hardware_specs SET status_id = 5 WHERE id = %s", (existente["id"],))
        return existente["id"]
    cur.execute("""
        INSERT INTO hardware_specs
        (tipo_equipo, marca, modelo, procesador, ram_gb, almacenamiento, sistema_operativo, pantalla, otros, status_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (tipo_equipo, marca, modelo, procesador, ram_gb, almacenamiento, sistema_operativo) DO NOTHING
        RETURNING id
    """, clave + tuple(extra))
    nueva = cur.fetchone()
    if nueva:
        return nueva["id"]
    cur.execute("""
        SELECT id FROM hardware_specs
        WHERE tipo_equipo = %s AND marca = %s AND modelo = %s AND procesador = %s
          AND ram_gb = %s AND almacenamiento = %s AND sistema_operativo = %s
    """, clave)
    return cur.fetchone()["id"]


@router.post("", status_code=201)
def crear_impresora(payload: PrinterIn):
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM computers WHERE numero_serie = %s", (payload.numero_serie,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="El número de serie ya está registrado.")
            _validar_compania_e_ip(cur, payload.company_id, payload.ip_address)

            spec_id = _spec_para(cur, payload.marca, payload.modelo)
            cur.execute("""
                INSERT INTO computers
                (hardware_spec_id, numero_serie, tipo_propiedad, estado_id, tarifa_mensual,
                 fecha_recepcion_proveedor, observaciones, anio_fabricacion)
                VALUES (%s, %s, %s, (SELECT id FROM statuses WHERE nombre = 'DISPONIBLE'), %s, %s, %s, %s)
                RETURNING id
            """, (spec_id, payload.numero_serie, payload.tipo_propiedad, payload.tarifa_mensual,
                  payload.fecha_recepcion_proveedor or date.today(), payload.observaciones,
                  payload.anio_fabricacion))
            computer_id = cur.fetchone()["id"]
            cur.execute("""
                INSERT INTO printers
                (computer_id, company_id, ip_address, hostname, area, ubicacion, es_color, proveedor, observaciones)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (computer_id, payload.company_id, payload.ip_address, payload.hostname, payload.area,
                  payload.ubicacion, payload.es_color, payload.proveedor, payload.observaciones))
            printer_id = cur.fetchone()["id"]
            return _impresora_por_id(cur, printer_id)
    except HTTPException:
        raise
    except psycopg2.errors.UniqueViolation as e:
        logger.info("Violacion de unicidad en POST /impresoras")
        if "ip" in (e.diag.constraint_name or ""):
            raise HTTPException(status_code=409, detail="La dirección IP ya está asignada a otra impresora.")
        raise HTTPException(status_code=400, detail="El número de serie ya está registrado.")
    except Exception:
        logger.exception("Error en POST /impresoras")
        raise HTTPException(status_code=500, detail="Error al crear la impresora.")


_CAMPOS_PRINTERS = ("company_id", "ip_address", "hostname", "area", "ubicacion", "es_color", "proveedor", "observaciones")


@router.put("/{printer_id}")
def actualizar_impresora(printer_id: int, payload: PrinterUpdate):
    """Actualización parcial: solo cambian los campos enviados. Marca/modelo usan copy-on-write de la
    especificación (hardware_specs es compartida por varios equipos)."""
    enviados = payload.model_fields_set
    datos = payload.model_dump()
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT p.id, p.computer_id, c.hardware_spec_id
                FROM printers p JOIN computers c ON c.id = p.computer_id
                LEFT JOIN statuses s ON s.id = c.estado_id
                WHERE p.id = %s AND COALESCE(s.nombre, '') <> 'ELIMINADO'
                FOR UPDATE OF p, c
            """, (printer_id,))
            actual = cur.fetchone()
            if not actual:
                raise HTTPException(status_code=404, detail="Impresora no encontrada")

            _validar_compania_e_ip(cur, datos["company_id"] if "company_id" in enviados else None,
                                   datos["ip_address"] if "ip_address" in enviados else None, printer_id)

            if "es_color" in enviados and datos["es_color"] is None:
                raise HTTPException(status_code=400, detail="es_color no puede ser nulo.")
            if "es_color" in enviados and not datos["es_color"]:
                cur.execute("SELECT 1 FROM printer_readings WHERE printer_id = %s AND contador_color > 0 LIMIT 1",
                            (printer_id,))
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail=(
                        "La impresora tiene lecturas con contador de color: no puede marcarse como monocromática."))

            sets = [c for c in _CAMPOS_PRINTERS if c in enviados]
            if sets:
                cur.execute(
                    "UPDATE printers SET " + ", ".join(f"{c} = %s" for c in sets) + ", updated_at = now() WHERE id = %s",
                    [datos[c] for c in sets] + [printer_id])
            else:
                cur.execute("UPDATE printers SET updated_at = now() WHERE id = %s", (printer_id,))

            # Especificación (copy-on-write)
            nueva_spec = actual["hardware_spec_id"]
            if datos["marca"] is not None or datos["modelo"] is not None:
                cur.execute("""
                    SELECT tipo_equipo, marca, modelo, procesador, ram_gb, almacenamiento, sistema_operativo,
                           pantalla, otros, status_id
                    FROM hardware_specs WHERE id = %s FOR UPDATE
                """, (actual["hardware_spec_id"],))
                hs = cur.fetchone()
                marca = datos["marca"] if datos["marca"] is not None else hs["marca"]
                modelo = datos["modelo"] if datos["modelo"] is not None else hs["modelo"]
                if (marca, modelo) != (hs["marca"], hs["modelo"]):
                    base = (hs["procesador"], hs["ram_gb"], hs["almacenamiento"], hs["sistema_operativo"])
                    clave = (hs["tipo_equipo"], marca, modelo) + base
                    cur.execute("""
                        SELECT id, status_id FROM hardware_specs
                        WHERE tipo_equipo = %s AND marca = %s AND modelo = %s AND procesador = %s
                          AND ram_gb = %s AND almacenamiento = %s AND sistema_operativo = %s AND id <> %s
                    """, clave + (actual["hardware_spec_id"],))
                    destino = cur.fetchone()
                    cur.execute("SELECT COUNT(*) AS n FROM computers WHERE hardware_spec_id = %s AND id <> %s",
                                (actual["hardware_spec_id"], actual["computer_id"]))
                    otros = cur.fetchone()["n"]
                    if destino:
                        nueva_spec = destino["id"]
                        if destino["status_id"] == 7:
                            cur.execute("UPDATE hardware_specs SET status_id = 5 WHERE id = %s", (nueva_spec,))
                    elif otros == 0:  # solo este equipo la usa: edición en sitio
                        cur.execute("UPDATE hardware_specs SET marca = %s, modelo = %s WHERE id = %s",
                                    (marca, modelo, actual["hardware_spec_id"]))
                    else:  # la comparten otros equipos: se crea una nueva y solo este apunta a ella
                        nueva_spec = _spec_para(cur, marca, modelo, base=base,
                                                extra=(hs["pantalla"], hs["otros"], hs["status_id"]))

            cur.execute("""
                UPDATE computers
                SET hardware_spec_id = %s,
                    tipo_propiedad = COALESCE(%s, tipo_propiedad),
                    tarifa_mensual = COALESCE(%s, tarifa_mensual)
                WHERE id = %s
            """, (nueva_spec, datos["tipo_propiedad"], datos["tarifa_mensual"], actual["computer_id"]))
            return _impresora_por_id(cur, printer_id)
    except HTTPException:
        raise
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="La dirección IP ya está asignada a otra impresora.")
    except Exception:
        logger.exception("Error en PUT /impresoras/{id}")
        raise HTTPException(status_code=500, detail="Error al actualizar la impresora.")


# ---------- lecturas de una impresora ----------
@router.get("/{printer_id}/lecturas")
def listar_lecturas(printer_id: int):
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM printers WHERE id = %s", (printer_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Impresora no encontrada")
            return _lecturas_de(cur, printer_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error en GET /impresoras/{id}/lecturas")
        raise HTTPException(status_code=500, detail="Error al obtener las lecturas.")


@router.post("/{printer_id}/lecturas", status_code=201)
def crear_lectura(printer_id: int, payload: ReadingIn, usuario: dict = Depends(usuario_actual)):
    periodo = _periodo_a_fecha(payload.periodo)
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            impresora = _bloquear_impresora(cur, printer_id)
            try:
                _validar_lectura(cur, impresora, periodo, payload.fecha_lectura, payload.contador_bn,
                                 payload.contador_color, payload.es_reinicio)
            except _ErrorLectura as e:
                raise _http(e)
            lectura_id = _insertar_lectura(cur, printer_id, periodo, payload, usuario)
            return _lectura_por_id(cur, lectura_id)
    except HTTPException:
        raise
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"Ya existe una lectura de {_mes_texto(periodo)} para esta impresora.")
    except Exception:
        logger.exception("Error en POST /impresoras/{id}/lecturas")
        raise HTTPException(status_code=500, detail="Error al registrar la lectura.")
