from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor
from datetime import date
import psycopg2
import logging

from auth import lectura_usuario_escritura_admin, usuario_actual
from schemas import (
    AccessoryIn, AccessoryTypeIn, AssignAccessoryIn, AssignComputerIn, CompanyIn, ComputerIn,
    HardwareIn, HardwareUpdate, PersonIn, PersonUpdate, StatusChangeIn,
)
from db import get_conn  # noqa: F401  (re-exportado para mantenimiento.py y pruebas)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/equipos", tags=["Equipos"], dependencies=[Depends(lectura_usuario_escritura_admin)])


def _texto_requerido(data: dict, campo: str) -> str:
    valor = str(data.get(campo, "")).strip()
    if not valor:
        raise HTTPException(status_code=400, detail=f"El campo {campo} es obligatorio.")
    return valor


def _entero_requerido(data: dict, campo: str) -> int:
    try:
        return int(data.get(campo))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"El campo {campo} debe ser un numero valido.")


def _norm(valor):
    """None y cadena vacía son equivalentes al comparar campos de texto opcionales."""
    return (valor or "").strip()


def _conflicto_especificacion(n: int, detalle: str):
    """409 con el número de equipos que se verían afectados (el frontend pide confirmación)."""
    return JSONResponse(status_code=409, content={"detail": detalle, "equipos_afectados": n})


def _equipos_que_usan_spec(cur, spec_id: int) -> int:
    cur.execute("""
        SELECT COUNT(*)
        FROM computers c
        LEFT JOIN statuses s ON s.id = c.estado_id
        WHERE c.hardware_spec_id = %s AND COALESCE(s.nombre, '') <> 'ELIMINADO'
    """, (spec_id,))
    return cur.fetchone()[0]


# Historial: los triggers de la BD insertan 'sistema' como usuario; se reatribuye al usuario autenticado
_COLUMNA_ENTIDAD_HISTORIAL = {"delivery_history": "computer_id", "accessory_history": "accessory_id"}


def _atribuir_movimiento(cur, tabla: str, entidad_id: int, tipo: str, usuario: dict) -> None:
    columna = _COLUMNA_ENTIDAD_HISTORIAL[tabla]  # lista blanca: nunca viene del cliente
    cur.execute(f"""
        UPDATE {tabla}
        SET usuario_registro = %s
        WHERE id = (
            SELECT MAX(id) FROM {tabla}
            WHERE {columna} = %s AND tipo_movimiento = %s AND usuario_registro = 'sistema'
        )
    """, (usuario["username"], entidad_id, tipo))


# =========================
# CREACIONES
# =========================
@router.post("/companies")
def create_company(payload: CompanyIn):
    logger.debug("POST /equipos/companies")
    data = payload.model_dump()
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO companies (nombre, status_id)
                VALUES (%s, (SELECT id FROM statuses WHERE nombre = 'ACTIVO'))
                RETURNING id
            """, (data["nombre"],))
            company_id = cur.fetchone()[0]
            conn.commit()
            return {"company_id": company_id}
        except Exception as e:
            conn.rollback()
            logger.exception("Error en /equipos/companies")
            raise HTTPException(status_code=500, detail="Error al crear compañía.")


@router.post("/people")
def create_person(payload: PersonIn):
    logger.debug("POST /equipos/people")
    data = payload.model_dump()
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                SELECT p.id, s.nombre
                FROM people p
                LEFT JOIN statuses s ON s.id = p.status_id
                WHERE p.cedula = %s
                FOR UPDATE OF p
            """, (data["cedula"],))
            existente = cur.fetchone()

            if existente:
                person_id, estado_actual = existente
                if estado_actual != "ELIMINADO":
                    raise HTTPException(status_code=400, detail="La cédula ya está registrada.")
                # Existía como eliminada: se reactiva con los datos nuevos
                cur.execute("""
                    UPDATE people
                    SET nombre = %s, cargo = %s, area = %s, email = %s, company_id = %s,
                        status_id = (SELECT id FROM statuses WHERE nombre = 'ACTIVO')
                    WHERE id = %s
                """, (data["nombre"], data["cargo"], data["area"], data["email"], data["company_id"], person_id))
                conn.commit()
                return {"person_id": person_id, "message": "La persona existía como eliminada y fue reactivada."}

            cur.execute("""
                INSERT INTO people
                (cedula, nombre, cargo, area, email, company_id, status_id)
                VALUES (%s, %s, %s, %s, %s, %s,
                        (SELECT id FROM statuses WHERE nombre = 'ACTIVO'))
                RETURNING id
            """, (
                data["cedula"],
                data["nombre"],
                data["cargo"],
                data["area"],
                data["email"],
                data["company_id"]
            ))
            person_id = cur.fetchone()[0]
            conn.commit()
            return {"person_id": person_id}
        except HTTPException:
            conn.rollback()
            raise
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status_code=400, detail="La cédula ya está registrada.")
        except psycopg2.errors.ForeignKeyViolation:
            conn.rollback()
            raise HTTPException(status_code=400, detail="La compañía indicada no existe.")
        except Exception:
            conn.rollback()
            logger.exception("Error en /equipos/people")
            raise HTTPException(status_code=500, detail="Error al crear persona.")


@router.post("/hardware")
def create_hardware(payload: HardwareIn):
    """Crea (o reutiliza) una especificación. pantalla y otros se persisten.
    status_id: se ignora a propósito. En hardware_specs solo importa ACTIVO (se usa) frente a ELIMINADO
    (oculta la spec), y el formulario envía un valor por defecto oculto (1 = NUEVO, estado de computadora)
    que el usuario no elige; el 98 % de las especificaciones existentes son ACTIVO. Se crea siempre ACTIVO.
    Si la especificación ya existe y se envían pantalla/otros distintos a los guardados, no se descartan en
    silencio: 409 con equipos_afectados salvo aplicar_a_todos=true."""
    logger.debug("POST /equipos/hardware")
    data = payload.model_dump()
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, status_id, pantalla, otros
                FROM hardware_specs
                WHERE tipo_equipo = %s
                  AND marca = %s
                  AND modelo = %s
                  AND procesador = %s
                  AND ram_gb = %s
                  AND almacenamiento = %s
                  AND sistema_operativo = %s
                LIMIT 1
                FOR UPDATE
            """, (
                data["tipo_equipo"],
                data["marca"],
                data["modelo"],
                data["procesador"],
                data["ram_gb"],
                data["almacenamiento"],
                data["sistema_operativo"]
            ))

            existing = cur.fetchone()

            if existing:
                hardware_id, status_id, pantalla_act, otros_act = existing

                # Solo cuenta lo que el cliente envía (no vacío) y difiere de lo guardado
                nueva_pantalla = _norm(data["pantalla"])
                nuevos_otros = _norm(data["otros"])
                difiere = (nueva_pantalla and nueva_pantalla != _norm(pantalla_act)) or \
                          (nuevos_otros and nuevos_otros != _norm(otros_act))
                if difiere:
                    n = _equipos_que_usan_spec(cur, hardware_id)
                    if n and not data["aplicar_a_todos"]:
                        conn.rollback()
                        return _conflicto_especificacion(
                            n, f"La especificación ya existe con otra pantalla/otros y la usan {n} equipos. "
                               "Envíe aplicar_a_todos=true para aplicarlos a todos.")
                    cur.execute("""
                        UPDATE hardware_specs
                        SET pantalla = COALESCE(NULLIF(%s, ''), pantalla),
                            otros = COALESCE(NULLIF(%s, ''), otros)
                        WHERE id = %s
                    """, (nueva_pantalla, nuevos_otros, hardware_id))

                # Si estaba eliminado, reactivar
                if status_id == 7:
                    cur.execute("""
                        UPDATE hardware_specs
                        SET status_id = 5
                        WHERE id = %s
                    """, (hardware_id,))
                conn.commit()

                return {
                    "hardware_id": hardware_id,
                    "message": "Hardware ya existía, se reutiliza."
                }

            cur.execute("""
                INSERT INTO hardware_specs
                (tipo_equipo, marca, modelo, procesador,
                 ram_gb, almacenamiento, sistema_operativo, pantalla, otros, status_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 5)
                RETURNING id
            """, (
                data["tipo_equipo"],
                data["marca"],
                data["modelo"],
                data["procesador"],
                data["ram_gb"],
                data["almacenamiento"],
                data["sistema_operativo"],
                data["pantalla"],
                data["otros"],
            ))

            hardware_id = cur.fetchone()[0]
            conn.commit()

            return {
                "hardware_id": hardware_id,
                "message": "Hardware creado correctamente."
            }

    except Exception:
        logger.exception("Error en /equipos/hardware")
        raise HTTPException(status_code=500, detail="Error al crear hardware.")


@router.post("/computers")
def create_computer(payload: ComputerIn):
    logger.debug("POST /equipos/computers")
    data = payload.model_dump()
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Validar hardware_spec_id
            cur.execute("""
                SELECT id, status_id
                FROM hardware_specs
                WHERE id = %s
            """, (data["hardware_spec_id"],))
            hw = cur.fetchone()

            if not hw:
                raise HTTPException(status_code=400, detail="El hardware_spec_id no existe.")

            if hw[1] == 7:
                raise HTTPException(status_code=400, detail="El hardware seleccionado está eliminado.")

            # Buscar si ya existe computadora con esa serie
            cur.execute("""
                SELECT id, estado_id
                FROM computers
                WHERE numero_serie = %s
                LIMIT 1
            """, (data["numero_serie"],))
            existing = cur.fetchone()

            if existing:
                computer_id, estado_id_actual = existing

                if estado_id_actual == 7:
                    cur.execute("""
                        UPDATE computers
                        SET hardware_spec_id = %s,
                            tipo_propiedad = %s,
                            estado_id = 2,
                            tarifa_mensual = %s,
                            fecha_recepcion_proveedor = %s,
                            anio_fabricacion = %s,
                            observaciones = %s
                        WHERE id = %s
                        RETURNING id
                    """, (
                        data["hardware_spec_id"],
                        data["tipo_propiedad"],
                        data["tarifa_mensual"],
                        data["fecha_recepcion_proveedor"],
                        data["anio_fabricacion"],
                        data.get("observaciones"),
                        computer_id
                    ))
                    reactivated_id = cur.fetchone()[0]
                    conn.commit()

                    return {
                        "computer_id": reactivated_id,
                        "message": "La computadora existía como eliminada y fue reactivada correctamente."
                    }

                raise HTTPException(status_code=400, detail="El número de serie ya está registrado.")

            cur.execute("""
                INSERT INTO computers
                (hardware_spec_id, numero_serie, tipo_propiedad,
                 estado_id, tarifa_mensual, fecha_recepcion_proveedor,
                 observaciones, anio_fabricacion)
                VALUES (%s, %s, %s, 2, %s, %s, %s, %s)
                RETURNING id
            """, (
                data["hardware_spec_id"],
                data["numero_serie"],
                data["tipo_propiedad"],
                data["tarifa_mensual"],
                data["fecha_recepcion_proveedor"],
                data.get("observaciones"),
                data["anio_fabricacion"]
            ))

            computer_id = cur.fetchone()[0]
            conn.commit()

            return {
                "computer_id": computer_id,
                "message": "Computadora creada correctamente."
            }

    except HTTPException:
        raise
    except psycopg2.errors.UniqueViolation as e:
        logger.info("Violacion de unicidad en /equipos/computers")
        raise HTTPException(status_code=400, detail="El número de serie ya está registrado.")
    except Exception as e:
        logger.exception("Error en /equipos/computers")
        raise HTTPException(status_code=500, detail="Error al crear computadora.")


@router.post("/accessory-types")
def create_accessory_type(payload: AccessoryTypeIn):
    logger.debug("POST /equipos/accessory-types")
    data = payload.model_dump()
    nombre = _texto_requerido(data, "nombre").upper()

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO accessory_types (nombre, status_id)
                VALUES (%s, (SELECT id FROM statuses WHERE nombre = 'ACTIVO'))
                RETURNING id
            """, (nombre,))
            accessory_type_id = cur.fetchone()[0]
            conn.commit()
            return {"accessory_type_id": accessory_type_id}
        except HTTPException:
            conn.rollback()
            raise
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status_code=400, detail="Ese tipo de accesorio ya esta registrado.")
        except Exception as e:
            conn.rollback()
            logger.exception("Error en /equipos/accessory-types")
            raise HTTPException(status_code=500, detail="Error al crear tipo de accesorio.")


@router.post("/accessories")
def create_accessory(payload: AccessoryIn):
    logger.debug("POST /equipos/accessories")
    data = payload.model_dump()
    accessory_type_id = _entero_requerido(data, "accessory_type_id")
    marca = _texto_requerido(data, "marca").upper()
    modelo = _texto_requerido(data, "modelo").upper()
    numero_serie = _texto_requerido(data, "numero_serie").upper()
    tipo_propiedad = _texto_requerido(data, "tipo_propiedad").upper()

    if tipo_propiedad not in {"PROPIO", "ARRIENDO"}:
        raise HTTPException(status_code=400, detail="El tipo de propiedad debe ser PROPIO o ARRIENDO.")

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                SELECT id
                FROM accessory_types
                WHERE id = %s
                  AND status_id <> (SELECT id FROM statuses WHERE nombre = 'ELIMINADO')
            """, (accessory_type_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="El tipo de accesorio seleccionado no existe o esta eliminado.")

            # Validar serial existente
            cur.execute("""
                SELECT id, estado_id
                FROM accessories
                WHERE numero_serie = %s
                LIMIT 1
            """, (numero_serie,))
            existing = cur.fetchone()

            if existing:
                accessory_id, estado_id_actual = existing

                # Si estaba eliminado, reactivar
                if estado_id_actual == 7:
                    cur.execute("""
                        UPDATE accessories
                        SET accessory_type_id = %s,
                            marca = %s,
                            modelo = %s,
                            estado_id = (SELECT id FROM statuses WHERE nombre = 'DISPONIBLE'),
                            tipo_propiedad = %s
                        WHERE id = %s
                        RETURNING id
                    """, (
                        accessory_type_id,
                        marca,
                        modelo,
                        tipo_propiedad,
                        accessory_id
                    ))
                    accessory_id = cur.fetchone()[0]
                    conn.commit()

                    return {
                        "accessory_id": accessory_id,
                        "message": "El accesorio existía como eliminado y fue reactivado correctamente."
                    }

                raise HTTPException(
                    status_code=400,
                    detail="El número de serie del accesorio ya está registrado."
                )

            cur.execute("""
                INSERT INTO accessories
                (accessory_type_id, marca, modelo, numero_serie, estado_id, tipo_propiedad)
                VALUES (
                    %s, %s, %s, %s,
                    (SELECT id FROM statuses WHERE nombre = 'DISPONIBLE'),
                    %s
                )
                RETURNING id
            """, (
                accessory_type_id,
                marca,
                modelo,
                numero_serie,
                tipo_propiedad
            ))

            accessory_id = cur.fetchone()[0]
            conn.commit()

            return {"accessory_id": accessory_id}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en /equipos/accessories")
            raise HTTPException(status_code=500, detail="Error al crear accesorio.")


# =========================
# ASIGNACIONES
# =========================
@router.post("/assign/computer")
def assign_computer(payload: AssignComputerIn, usuario: dict = Depends(usuario_actual)):
    logger.debug("POST /equipos/assign/computer")
    data = payload.model_dump()
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Bloquear la computadora para evitar doble asignación concurrente
            cur.execute("""
                SELECT c.id
                FROM computers c
                JOIN statuses s ON c.estado_id = s.id
                WHERE c.id = %s
                  AND s.nombre IN ('DISPONIBLE', 'NUEVO')
                FOR UPDATE
            """, (data["computer_id"],))
            computer = cur.fetchone()

            if not computer:
                raise HTTPException(
                    status_code=400,
                    detail="Computadora no disponible (Debe estar DISPONIBLE o NUEVO)"
                )

            # Validar si ya existe una asignación activa para esa computadora
            cur.execute("""
                SELECT id
                FROM computer_assignments
                WHERE computer_id = %s
                  AND activo = TRUE
                LIMIT 1
            """, (data["computer_id"],))
            existing_assignment = cur.fetchone()

            if existing_assignment:
                raise HTTPException(
                    status_code=400,
                    detail="La computadora ya tiene una asignación activa"
                )

            # Bloquear la fila de la persona: serializa asignaciones concurrentes de la misma persona
            # (orden de bloqueo fijo: computadora y luego persona, sin riesgo de interbloqueo)
            cur.execute("""
                SELECT s.nombre
                FROM people p
                LEFT JOIN statuses s ON s.id = p.status_id
                WHERE p.id = %s
                FOR UPDATE OF p
            """, (data["person_id"],))
            persona = cur.fetchone()
            if not persona or persona[0] == "ELIMINADO":
                raise HTTPException(status_code=400, detail="La persona no existe o está eliminada.")

            # Validar si la persona ya tiene una computadora activa
            cur.execute("""
                SELECT id
                FROM computer_assignments
                WHERE person_id = %s
                  AND activo = TRUE
                LIMIT 1
            """, (data["person_id"],))
            person_assignment = cur.fetchone()

            if person_assignment:
                raise HTTPException(
                    status_code=400,
                    detail="La persona ya tiene una computadora asignada"
                )

            # Insertar asignación activa
            cur.execute("""
                INSERT INTO computer_assignments
                (computer_id, person_id, fecha_asignacion, activo)
                VALUES (%s, %s, %s, TRUE)
                RETURNING id
            """, (data["computer_id"], data["person_id"], date.today()))
            assignment_id = cur.fetchone()[0]

            # Actualizar estado del equipo
            cur.execute("""
                UPDATE computers
                SET estado_id = (SELECT id FROM statuses WHERE nombre = 'ASIGNADO')
                WHERE id = %s
            """, (data["computer_id"],))
            _atribuir_movimiento(cur, "delivery_history", data["computer_id"], "ENTREGA", usuario)

            conn.commit()

            return {
                "message": "Computadora asignada exitosamente",
                "assignment_id": assignment_id
            }

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en /equipos/assign/computer")
            raise HTTPException(status_code=500, detail="Error al asignar computadora.")


@router.post("/assign/accessory")
def assign_accessory(payload: AssignAccessoryIn, usuario: dict = Depends(usuario_actual)):
    logger.debug("POST /equipos/assign/accessory")
    data = payload.model_dump()
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Bloquear accesorio
            cur.execute("""
                SELECT a.id
                FROM accessories a
                JOIN statuses s ON a.estado_id = s.id
                WHERE a.id = %s
                  AND s.nombre IN ('DISPONIBLE', 'NUEVO')
                FOR UPDATE
            """, (data["accessory_id"],))
            accessory = cur.fetchone()

            if not accessory:
                raise HTTPException(
                    status_code=400,
                    detail="Accesorio no disponible (Debe estar DISPONIBLE o NUEVO)"
                )

            # Bloquear la persona (serializa contra DELETE /people y otras asignaciones)
            cur.execute("""
                SELECT s.nombre
                FROM people p
                LEFT JOIN statuses s ON s.id = p.status_id
                WHERE p.id = %s
                FOR UPDATE OF p
            """, (data["person_id"],))
            persona = cur.fetchone()
            if not persona or persona[0] == "ELIMINADO":
                raise HTTPException(status_code=400, detail="La persona no existe o está eliminada.")

            # Validar relación duplicada activa
            cur.execute("""
                SELECT id
                FROM person_accessories
                WHERE person_id = %s
                  AND accessory_id = %s
                  AND activo = TRUE
                LIMIT 1
            """, (data["person_id"], data["accessory_id"]))
            existing_relation = cur.fetchone()

            if existing_relation:
                raise HTTPException(
                    status_code=400,
                    detail="Ese accesorio ya está asignado a esa persona"
                )

            # Validar que no esté asignado a otra persona
            cur.execute("""
                SELECT id
                FROM person_accessories
                WHERE accessory_id = %s
                  AND activo = TRUE
                LIMIT 1
            """, (data["accessory_id"],))
            existing_active_accessory = cur.fetchone()

            if existing_active_accessory:
                raise HTTPException(
                    status_code=400,
                    detail="El accesorio ya tiene una asignación activa"
                )

            # Insertar asignación
            cur.execute("""
                INSERT INTO person_accessories
                (person_id, accessory_id, fecha_asignacion, activo)
                VALUES (%s, %s, %s, TRUE)
                RETURNING id
            """, (data["person_id"], data["accessory_id"], date.today()))
            relation_id = cur.fetchone()[0]

            # Actualizar estado del accesorio
            cur.execute("""
                UPDATE accessories
                SET estado_id = (SELECT id FROM statuses WHERE nombre = 'ASIGNADO')
                WHERE id = %s
            """, (data["accessory_id"],))
            _atribuir_movimiento(cur, "accessory_history", data["accessory_id"], "ENTREGA", usuario)

            conn.commit()

            return {
                "message": "Accesorio asignado correctamente",
                "relation_id": relation_id
            }

        except HTTPException:
            conn.rollback()
            raise
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status_code=400, detail="El accesorio ya tiene una asignación activa")
        except Exception as e:
            conn.rollback()
            logger.exception("Error en /equipos/assign/accessory")
            raise HTTPException(status_code=500, detail="Error al asignar accesorio.")


# =========================
# DELETE = ELIMINADO
# =========================
@router.delete("/computers/{serial}")
def delete_computer(serial: str, usuario: dict = Depends(usuario_actual)):
    logger.debug(f"DELETE /equipos/computers/{serial}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Bloqueo de la computadora ANTES de tocar asignaciones: mismo orden que assign/computer
            # (computadora y luego persona), así una asignación concurrente no queda huérfana.
            cur.execute("""
                SELECT id
                FROM computers
                WHERE numero_serie = %s
                FOR UPDATE
            """, (serial,))
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Equipo no encontrado")

            computer_id = row[0]

            # Cerrar asignaciones activas
            cur.execute("""
                UPDATE computer_assignments
                SET activo = FALSE,
                    fecha_desasignacion = CURRENT_DATE
                WHERE computer_id = %s
                  AND activo = TRUE
            """, (computer_id,))
            if cur.rowcount:
                _atribuir_movimiento(cur, "delivery_history", computer_id, "DEVOLUCION", usuario)

            # Eliminar lógicamente
            cur.execute("""
                UPDATE computers
                SET estado_id = 7
                WHERE id = %s
            """, (computer_id,))

            conn.commit()
            return {"message": f"Computadora {serial} eliminada correctamente"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en DELETE /equipos/computers/{serial}")
            raise HTTPException(status_code=500, detail="Error al eliminar computadora.")


@router.delete("/accessories/{id}")
def delete_accessory(id: int, usuario: dict = Depends(usuario_actual)):
    logger.debug(f"DELETE /equipos/accessories/{id}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                SELECT s.nombre
                FROM accessories a
                LEFT JOIN statuses s ON s.id = a.estado_id
                WHERE a.id = %s
                FOR UPDATE OF a
            """, (id,))
            fila = cur.fetchone()
            if not fila or fila[0] == "ELIMINADO":
                raise HTTPException(status_code=404, detail="Accesorio no encontrado")

            # Si estaba asignado: registrar la DEVOLUCION con el usuario autenticado y cerrar la relación
            cur.execute("""
                SELECT person_id
                FROM person_accessories
                WHERE accessory_id = %s
                  AND activo = TRUE
                FOR UPDATE
            """, (id,))
            relacion = cur.fetchone()
            if relacion:
                cur.execute("""
                    INSERT INTO accessory_history
                    (accessory_id, person_id, tipo_movimiento, fecha_movimiento, usuario_registro)
                    VALUES (%s, %s, 'DEVOLUCION', CURRENT_DATE, %s)
                """, (id, relacion[0], usuario["username"]))
                cur.execute("""
                    UPDATE person_accessories
                    SET activo = FALSE,
                        fecha_desasignacion = CURRENT_DATE
                    WHERE accessory_id = %s
                      AND activo = TRUE
                """, (id,))

            cur.execute("""
                UPDATE accessories
                SET estado_id = (SELECT id FROM statuses WHERE nombre = 'ELIMINADO')
                WHERE id = %s
            """, (id,))

            conn.commit()
            return {"message": "Accesorio eliminado"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en DELETE /equipos/accessories/{id}")
            raise HTTPException(status_code=500, detail="Error al eliminar accesorio.")


# =========================
# VISTAS
# =========================
@router.get("/vista/equipo-completo")
def vista_equipo_completo():
    logger.debug("GET /equipos/vista/equipo-completo")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("SELECT * FROM vw_equipo_completo ORDER BY empleado")
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/vista/equipo-completo")
            raise HTTPException(status_code=500, detail="Error al consultar vista equipo completo.")


@router.get("/vista/equipo-completo/{cedula}")
def vista_equipo_por_cedula(cedula: str):
    logger.debug(f"GET /equipos/vista/equipo-completo/{cedula}")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("SELECT * FROM vw_equipo_completo WHERE cedula = %s", (cedula,))
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/vista/equipo-completo/{cedula}")
            raise HTTPException(status_code=500, detail="Error al consultar equipo por cédula.")

@router.get("/vista/inventario-general")
def vista_inventario_general():
    logger.debug("GET /equipos/vista/inventario-general")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                WITH ultima_asignacion AS (
                    SELECT DISTINCT ON (ca.computer_id)
                        ca.computer_id,
                        ca.person_id,
                        ca.fecha_asignacion,
                        ca.id
                    FROM computer_assignments ca
                    WHERE ca.activo = TRUE
                    ORDER BY ca.computer_id, ca.fecha_asignacion DESC, ca.id DESC
                )
                SELECT
                    c.id,
                    c.hardware_spec_id,

                    c.numero_serie,

                    hs.tipo_equipo,
                    hs.tipo_equipo AS equipo,

                    hs.marca,
                    hs.modelo,
                    hs.procesador,
                    hs.ram_gb,
                    hs.almacenamiento,
                    hs.sistema_operativo,
                    hs.pantalla,
                    hs.otros,
                    hs.status_id,

                    c.tipo_propiedad,
                    c.tipo_propiedad AS propiedad,

                    c.tarifa_mensual,
                    c.fecha_recepcion_proveedor,
                    c.observaciones,
                    c.anio_fabricacion,

                    s.id AS estado_id,
                    s.nombre AS estado,
                    s.nombre AS estado_computadora,
                    s.nombre AS status_nombre,

                    p.id AS person_id,
                    p.id AS id_persona,
                    p.nombre AS usuario_actual,
                    p.cedula,
                    p.cargo,
                    p.area,
                    p.email,
                    p.company_id,

                    comp.nombre AS company_nombre

                FROM computers c
                JOIN hardware_specs hs
                    ON c.hardware_spec_id = hs.id
                JOIN statuses s
                    ON c.estado_id = s.id
                LEFT JOIN ultima_asignacion ua
                    ON ua.computer_id = c.id
                LEFT JOIN people p
                    ON p.id = ua.person_id
                LEFT JOIN companies comp
                    ON comp.id = p.company_id
                WHERE s.nombre <> 'ELIMINADO'
                ORDER BY c.numero_serie;
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/vista/inventario-general")
            raise HTTPException(status_code=500, detail="Error al consultar inventario general.")


@router.get("/vista/computadora-asignada")
def computadoras_asignadas():
    logger.debug("GET /equipos/vista/computadora-asignada")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("SELECT * FROM vw_computadora_asignada")
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/vista/computadora-asignada")
            raise HTTPException(status_code=500, detail="Error al consultar computadoras asignadas.")


@router.get("/vista/accesorios-por-persona/{cedula}")
def accesorios_por_persona(cedula: str):
    logger.debug(f"GET /equipos/vista/accesorios-por-persona/{cedula}")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT
                    pa.id AS relation_id,
                    a.id AS accessory_id,
                    p.id AS person_id,
                    p.cedula,
                    p.nombre AS empleado,
                    at.nombre AS tipo_accesorio,
                    a.marca,
                    a.modelo,
                    a.numero_serie,
                    a.tipo_propiedad,
                    pa.fecha_asignacion,
                    pa.fecha_desasignacion
                FROM person_accessories pa
                JOIN people p ON pa.person_id = p.id
                JOIN accessories a ON pa.accessory_id = a.id
                JOIN accessory_types at ON a.accessory_type_id = at.id
                JOIN statuses s ON a.estado_id = s.id
                WHERE p.cedula = %s
                  AND pa.activo = TRUE
                  AND s.nombre <> 'ELIMINADO'
                ORDER BY at.nombre, a.marca, a.modelo
            """, (cedula,))
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/vista/accesorios-por-persona/{cedula}")
            raise HTTPException(status_code=500, detail="Error al consultar accesorios por persona.")


# =========================
# GET CONSULTAS API
# =========================
@router.get("/catalogos/statuses")
def get_statuses():
    logger.debug("GET /equipos/catalogos/statuses")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT id, nombre
                FROM statuses
                WHERE nombre <> 'ELIMINADO'
                ORDER BY nombre
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/catalogos/statuses")
            raise HTTPException(status_code=500, detail="Error al obtener statuses.")


@router.get("/companies")
def get_companies():
    logger.debug("GET /equipos/companies")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT c.id, c.nombre
                FROM companies c
                JOIN statuses s ON c.status_id = s.id
                WHERE s.nombre <> 'ELIMINADO'
                ORDER BY c.nombre
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/companies")
            raise HTTPException(status_code=500, detail="Error al obtener compañías.")


@router.get("/people")
def get_people():
    logger.debug("GET /equipos/people")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT
                    p.id,
                    p.cedula,
                    p.nombre,
                    p.cargo,
                    p.area,
                    p.email,
                    p.company_id,
                    c.nombre AS company_nombre,
                    p.status_id,
                    s.nombre AS status_nombre
                FROM people p
                JOIN companies c ON p.company_id = c.id
                JOIN statuses s ON p.status_id = s.id
                WHERE s.nombre <> 'ELIMINADO'
                ORDER BY p.nombre
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/people")
            raise HTTPException(status_code=500, detail="Error al obtener personas.")


@router.get("/hardware")
def get_hardware():
    logger.debug("GET /equipos/hardware")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT id, tipo_equipo, marca, modelo
                FROM hardware_specs
                WHERE status_id <> (SELECT id FROM statuses WHERE nombre = 'ELIMINADO')
                ORDER BY marca, modelo
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/hardware")
            raise HTTPException(status_code=500, detail="Error al obtener hardware.")


@router.get("/accessory-types")
def get_accessory_types():
    logger.debug("GET /equipos/accessory-types")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT at.id, at.nombre
                FROM accessory_types at
                JOIN statuses s ON at.status_id = s.id
                WHERE s.nombre <> 'ELIMINADO'
                ORDER BY at.nombre
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/accessory-types")
            raise HTTPException(status_code=500, detail="Error al obtener tipos de accesorio.")


@router.get("/accessories/disponibles")
def get_accessories_disponibles():
    logger.debug("GET /equipos/accessories/disponibles")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT
                    a.id,
                    at.nombre AS tipo,
                    a.marca,
                    a.modelo,
                    a.numero_serie,
                    a.tipo_propiedad
                FROM accessories a
                JOIN statuses s ON a.estado_id = s.id
                JOIN accessory_types at ON a.accessory_type_id = at.id
                WHERE s.nombre IN ('DISPONIBLE', 'NUEVO')
                ORDER BY at.nombre
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/accessories/disponibles")
            raise HTTPException(status_code=500, detail="Error al obtener accesorios disponibles.")


@router.get("/computers/disponibles")
def get_computers_disponibles():
    logger.debug("GET /equipos/computers/disponibles")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT
                    c.id,
                    c.numero_serie,
                    hs.tipo_equipo,
                    hs.marca,
                    hs.modelo
                FROM computers c
                JOIN statuses s ON c.estado_id = s.id
                JOIN hardware_specs hs ON c.hardware_spec_id = hs.id
                WHERE s.nombre IN ('DISPONIBLE', 'NUEVO')
                ORDER BY c.numero_serie
            """)
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/computers/disponibles")
            raise HTTPException(status_code=500, detail="Error al obtener computadoras disponibles.")


# Lista positiva: los únicos estados que este endpoint puede fijar en una computadora. El frontend solo
# usa BAJA (Activos.js) y DISPONIBLE (filtro/liberación). La tabla statuses es global y trae estados de
# otras entidades (ACTIVO, INACTIVO...), que no son válidos para computadoras. No existe MANTENIMIENTO en
# statuses (no se inventan estados: sería un cambio de datos compartido con producción).
# ELIMINADO y ASIGNADO tienen su propio flujo (DELETE y assign/computer).
_ESTADOS_DESTINO_COMPUTADORA = {"DISPONIBLE", "BAJA"}
_ESTADOS_CON_FLUJO_PROPIO = {
    "ELIMINADO": "Para eliminar un equipo use DELETE /equipos/computers/{serie}.",
    "ASIGNADO": "Para asignar un equipo use POST /equipos/assign/computer.",
}
# Transiciones permitidas por estado actual (mismo estado no es una transición)
_TRANSICIONES_COMPUTADORA = {
    "NUEVO": {"DISPONIBLE", "BAJA"},
    "DISPONIBLE": {"BAJA"},
    "ASIGNADO": {"DISPONIBLE", "BAJA"},  # cierra la asignación activa
    "BAJA": {"DISPONIBLE"},              # reactivar un equipo dado de baja
}


@router.put("/computers/{serial}/status")
def change_computer_status(serial: str, payload: StatusChangeIn, usuario: dict = Depends(usuario_actual)):
    logger.debug(f"PUT /equipos/computers/{serial}/status")
    nuevo_estado = payload.nuevo_estado.upper()

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT id FROM statuses WHERE nombre = %s", (nuevo_estado,))
            estado = cur.fetchone()
            if not estado:
                raise HTTPException(status_code=400, detail=f"El estado '{nuevo_estado}' no existe.")
            if nuevo_estado in _ESTADOS_CON_FLUJO_PROPIO:
                raise HTTPException(status_code=400, detail=_ESTADOS_CON_FLUJO_PROPIO[nuevo_estado])
            if nuevo_estado not in _ESTADOS_DESTINO_COMPUTADORA:
                raise HTTPException(
                    status_code=400,
                    detail="Estado no válido para computadoras. Permitidos: "
                           + ", ".join(sorted(_ESTADOS_DESTINO_COMPUTADORA)) + ".")
            estado_id = estado[0]

            cur.execute("""
                SELECT c.id, s.nombre
                FROM computers c
                LEFT JOIN statuses s ON s.id = c.estado_id
                WHERE c.numero_serie = %s
                FOR UPDATE OF c
            """, (serial,))
            row = cur.fetchone()

            if not row or row[1] == "ELIMINADO":
                raise HTTPException(status_code=404, detail="Equipo no encontrado")

            computer_id = row[0]
            permitidos = _TRANSICIONES_COMPUTADORA.get(row[1])
            if permitidos is not None and nuevo_estado not in permitidos:
                raise HTTPException(
                    status_code=400,
                    detail=f"Transición no permitida: {row[1]} -> {nuevo_estado}.")

            # Ningún estado permitido es ASIGNADO: si estaba asignado, se cierra la asignación activa
            cur.execute("""
                UPDATE computer_assignments
                SET activo = FALSE,
                    fecha_desasignacion = CURRENT_DATE
                WHERE computer_id = %s
                  AND activo = TRUE
            """, (computer_id,))
            if cur.rowcount:
                _atribuir_movimiento(cur, "delivery_history", computer_id, "DEVOLUCION", usuario)

            cur.execute("UPDATE computers SET estado_id = %s WHERE id = %s", (estado_id, computer_id))
            if nuevo_estado == "BAJA":
                _atribuir_movimiento(cur, "delivery_history", computer_id, "BAJA", usuario)

            conn.commit()
            return {"message": f"Equipo {serial} actualizado a {nuevo_estado}"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en PUT /equipos/computers/{serial}/status")
            raise HTTPException(status_code=500, detail="Error al cambiar estado.")


@router.get("/accesorios/persona/{cedula}")
def get_accesorios_persona(cedula: str):
    logger.debug(f"GET /equipos/accesorios/persona/{cedula}")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("""
                SELECT
                    pa.id AS relation_id,
                    a.id AS accessory_id,
                    p.id AS person_id,
                    p.cedula,
                    p.nombre AS empleado,
                    at.nombre AS tipo_accesorio,
                    a.marca,
                    a.modelo,
                    a.numero_serie,
                    a.tipo_propiedad,
                    pa.fecha_asignacion,
                    pa.fecha_desasignacion
                FROM person_accessories pa
                JOIN people p ON pa.person_id = p.id
                JOIN accessories a ON pa.accessory_id = a.id
                JOIN accessory_types at ON a.accessory_type_id = at.id
                JOIN statuses s ON a.estado_id = s.id
                WHERE p.cedula = %s
                  AND pa.activo = TRUE
                  AND s.nombre <> 'ELIMINADO'
                ORDER BY at.nombre, a.marca, a.modelo
            """, (cedula,))
            return cur.fetchall()
        except Exception as e:
            logger.exception("Error en GET /equipos/accesorios/persona/{cedula}")
            raise HTTPException(status_code=500, detail="Error al obtener accesorios de persona.")


@router.put("/unassign/accessory/{accessory_id}")
def unassign_accessory(accessory_id: int, usuario: dict = Depends(usuario_actual)):
    logger.debug(f"PUT /equipos/unassign/accessory/{accessory_id}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                SELECT person_id
                FROM person_accessories
                WHERE accessory_id = %s
                  AND activo = TRUE
                FOR UPDATE
            """, (accessory_id,))
            relation = cur.fetchone()

            if not relation:
                raise HTTPException(status_code=404, detail="El accesorio no tiene una asignacion activa")

            person_id = relation[0]

            cur.execute("""
                INSERT INTO accessory_history
                (accessory_id, person_id, tipo_movimiento, fecha_movimiento, usuario_registro)
                VALUES (%s, %s, 'DEVOLUCION', CURRENT_DATE, %s)
            """, (accessory_id, person_id, usuario["username"]))

            cur.execute("""
                UPDATE person_accessories
                SET activo = FALSE,
                    fecha_desasignacion = CURRENT_DATE
                WHERE accessory_id = %s
                  AND activo = TRUE
            """, (accessory_id,))

            cur.execute("""
                UPDATE accessories
                SET estado_id = (SELECT id FROM statuses WHERE nombre = 'DISPONIBLE')
                WHERE id = %s
            """, (accessory_id,))

            conn.commit()
            return {"message": "Accesorio liberado correctamente"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en PUT /equipos/unassign/accessory/{accessory_id}")
            raise HTTPException(status_code=500, detail="Error al liberar accesorio.")


@router.post("/unassign/full/{person_id}")
def unassign_full(person_id: int, usuario: dict = Depends(usuario_actual)):
    logger.debug(f"POST /equipos/unassign/full/{person_id}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT id FROM people WHERE id = %s FOR UPDATE", (person_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Persona no encontrada")

            # ======================
            # 1. Buscar computadora activa
            # ======================
            cur.execute("""
                SELECT computer_id
                FROM computer_assignments
                WHERE person_id = %s
                  AND activo = TRUE
                FOR UPDATE
            """, (person_id,))
            comp = cur.fetchone()

            if comp:
                computer_id = comp[0]

                # Desasignar computadora. El historial DEVOLUCION lo inserta el trigger
                # tg_historial_devolucion (insertarlo a mano lo duplicaba); aquí solo se atribuye.
                cur.execute("""
                    UPDATE computer_assignments
                    SET activo = FALSE,
                        fecha_desasignacion = CURRENT_DATE
                    WHERE computer_id = %s
                      AND activo = TRUE
                """, (computer_id,))
                _atribuir_movimiento(cur, "delivery_history", computer_id, "DEVOLUCION", usuario)

                # Liberar computadora
                cur.execute("""
                    UPDATE computers
                    SET estado_id = (
                        SELECT id FROM statuses WHERE nombre = 'DISPONIBLE'
                    )
                    WHERE id = %s
                """, (computer_id,))

            # ======================
            # 2. Accesorios activos
            # ======================
            cur.execute("""
                SELECT accessory_id
                FROM person_accessories
                WHERE person_id = %s
                  AND activo = TRUE
            """, (person_id,))
            accesorios = [a[0] for a in cur.fetchall()]

            for acc in accesorios:
                cur.execute("""
                    INSERT INTO accessory_history
                    (accessory_id, person_id, tipo_movimiento, fecha_movimiento, usuario_registro)
                    VALUES (%s, %s, 'DEVOLUCION', CURRENT_DATE, %s)
                """, (acc, person_id, usuario["username"]))

            # Cerrar relaciones activas, no borrar histórico a lo bruto
            cur.execute("""
                UPDATE person_accessories
                SET activo = FALSE,
                    fecha_desasignacion = CURRENT_DATE
                WHERE person_id = %s
                  AND activo = TRUE
            """, (person_id,))

            if accesorios:
                cur.execute("""
                    UPDATE accessories
                    SET estado_id = (
                        SELECT id FROM statuses WHERE nombre = 'DISPONIBLE'
                    )
                    WHERE id = ANY(%s)
                """, (accesorios,))

            conn.commit()
            return {"mensaje": "Equipo completo desasignado"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en POST /equipos/unassign/full/{person_id}")
            raise HTTPException(status_code=500, detail="Error en desasignación completa.")


@router.put("/unassign/computer/{computer_id}")
def unassign_computer(computer_id: int, usuario: dict = Depends(usuario_actual)):
    logger.debug(f"PUT /equipos/unassign/computer/{computer_id}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Cerrar asignación activa
            cur.execute("""
                UPDATE computer_assignments
                SET activo = FALSE,
                    fecha_desasignacion = %s
                WHERE computer_id = %s
                  AND activo = TRUE
            """, (date.today(), computer_id))
            if cur.rowcount:
                _atribuir_movimiento(cur, "delivery_history", computer_id, "DEVOLUCION", usuario)

            # Poner equipo disponible
            cur.execute("""
                UPDATE computers
                SET estado_id = (SELECT id FROM statuses WHERE nombre = 'DISPONIBLE')
                WHERE id = %s
            """, (computer_id,))

            conn.commit()
            return {"message": "Computadora liberada correctamente"}

        except Exception as e:
            conn.rollback()
            logger.exception("Error en PUT /equipos/unassign/computer/{computer_id}")
            raise HTTPException(status_code=500, detail="Error al liberar computadora.")


# =========================
# UPDATES
# =========================
@router.put("/people/{id}")
def update_person(id: int, payload: PersonUpdate):
    logger.debug(f"PUT /equipos/people/{id}")
    data = payload.model_dump()
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                SELECT s.nombre
                FROM people p
                LEFT JOIN statuses s ON s.id = p.status_id
                WHERE p.id = %s
                FOR UPDATE OF p
            """, (id,))
            fila = cur.fetchone()
            if not fila or fila[0] == "ELIMINADO":
                raise HTTPException(status_code=404, detail="Persona no encontrada")

            if data["status_id"] is not None:
                cur.execute("SELECT nombre FROM statuses WHERE id = %s", (data["status_id"],))
                estado = cur.fetchone()
                if not estado:
                    raise HTTPException(status_code=400, detail="El estado indicado no existe.")
                if estado[0] == "ELIMINADO":
                    raise HTTPException(status_code=400, detail="Para eliminar a una persona use DELETE /equipos/people/{id}.")

            cur.execute("""
                UPDATE people
                SET cedula = %s,
                    nombre = %s,
                    cargo = %s,
                    area = %s,
                    email = %s,
                    company_id = %s,
                    status_id = COALESCE(%s, status_id)
                WHERE id = %s
            """, (
                data["cedula"],
                data["nombre"],
                data["cargo"],
                data["area"],
                data["email"],
                data["company_id"],
                data["status_id"],
                id
            ))

            conn.commit()
            return {"message": f"Persona {id} actualizada correctamente"}

        except HTTPException:
            conn.rollback()
            raise
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status_code=400, detail="La cédula ya está registrada.")
        except psycopg2.errors.ForeignKeyViolation:
            conn.rollback()
            raise HTTPException(status_code=400, detail="La compañía indicada no existe.")
        except Exception:
            conn.rollback()
            logger.exception("Error en PUT /equipos/people/{id}")
            raise HTTPException(status_code=500, detail="Error al actualizar persona.")


@router.delete("/people/{id}")
def delete_person(id: int):
    """Borrado lógico (estado ELIMINADO, igual que equipos y accesorios). El historial conserva la
    referencia a la persona. 409 si aun tiene equipos o accesorios asignados."""
    logger.debug(f"DELETE /equipos/people/{id}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # El bloqueo de la fila serializa contra assign/* (que tambien la bloquean)
            cur.execute("""
                SELECT s.nombre
                FROM people p
                LEFT JOIN statuses s ON s.id = p.status_id
                WHERE p.id = %s
                FOR UPDATE OF p
            """, (id,))
            fila = cur.fetchone()
            if not fila or fila[0] == "ELIMINADO":
                raise HTTPException(status_code=404, detail="Persona no encontrada")

            cur.execute("SELECT 1 FROM computer_assignments WHERE person_id = %s AND activo = TRUE LIMIT 1", (id,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="La persona tiene una computadora asignada. Libérela antes de eliminarla.")
            cur.execute("SELECT 1 FROM person_accessories WHERE person_id = %s AND activo = TRUE LIMIT 1", (id,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="La persona tiene accesorios asignados. Libérelos antes de eliminarla.")

            cur.execute("""
                UPDATE people
                SET status_id = (SELECT id FROM statuses WHERE nombre = 'ELIMINADO')
                WHERE id = %s
            """, (id,))
            conn.commit()
            return {"message": "Persona eliminada"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            logger.exception("Error en DELETE /equipos/people/{id}")
            raise HTTPException(status_code=500, detail="Error al eliminar persona.")


_CAMPOS_CLAVE_HW = ("tipo_equipo", "marca", "modelo", "procesador", "ram_gb", "almacenamiento", "sistema_operativo")


@router.put("/hardware/{id}")
def update_hardware(id: int, payload: HardwareUpdate):
    """Edita una especificación de hardware con copy-on-write.

    hardware_specs es compartida por varios equipos (uniq_hardware_specs sobre los 7 campos clave):
      - Cambian campos clave: nunca afectan a otros equipos. Si solo este equipo usa la spec y no hay otra
        idéntica se edita en sitio; si existe una idéntica el equipo pasa a usarla; si otros equipos comparten
        la actual se crea una nueva y solo este equipo apunta a ella.
      - Campos NO clave (pantalla, otros, status_id): viven en la fila compartida (el índice único impide
        duplicarla). Si la spec resultante la usan varios equipos, el cambio los afecta a todos, así que se
        responde 409 {"detail", "equipos_afectados": N} salvo aplicar_a_todos=true. Esto también aplica al
        reutilizar una spec existente cuya pantalla/otros/status difieren de lo enviado: nunca se descartan datos.
    pantalla/otros/status_id en None significan "no cambiar". El equipo se identifica con `numero_serie`
    (opcional si la spec la usa un único equipo).
    """
    logger.debug(f"PUT /equipos/hardware/{id}")
    data = payload.model_dump()
    clave_nueva = tuple(data[c] for c in _CAMPOS_CLAVE_HW)

    def cambios_no_clave(pantalla, otros, status):
        """True si lo enviado difiere de lo guardado en la spec destino."""
        return ((data["pantalla"] is not None and _norm(data["pantalla"]) != _norm(pantalla))
                or (data["otros"] is not None and _norm(data["otros"]) != _norm(otros))
                or (data["status_id"] is not None and data["status_id"] != status))

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                SELECT tipo_equipo, marca, modelo, procesador, ram_gb, almacenamiento, sistema_operativo,
                       status_id, pantalla, otros
                FROM hardware_specs
                WHERE id = %s
                FOR UPDATE
            """, (id,))
            actual = cur.fetchone()
            if not actual:
                raise HTTPException(status_code=404, detail="Hardware no encontrado")
            clave_actual = tuple(actual[:7])
            status_actual, pantalla_actual, otros_actual = actual[7], actual[8], actual[9]
            nuevo_status = data["status_id"] if data["status_id"] is not None else status_actual
            nueva_pantalla = data["pantalla"] if data["pantalla"] is not None else pantalla_actual
            nuevos_otros = data["otros"] if data["otros"] is not None else otros_actual

            # Equipos (no eliminados) que usan esta especificación
            cur.execute("""
                SELECT c.id, c.numero_serie
                FROM computers c
                LEFT JOIN statuses s ON s.id = c.estado_id
                WHERE c.hardware_spec_id = %s
                  AND COALESCE(s.nombre, '') <> 'ELIMINADO'
                ORDER BY c.id
                FOR UPDATE OF c
            """, (id,))
            usuarios = cur.fetchall()

            computer_id = None
            if data["numero_serie"]:
                for cid, serie in usuarios:
                    if serie == data["numero_serie"]:
                        computer_id = cid
                if computer_id is None:
                    raise HTTPException(status_code=404, detail="El equipo indicado no usa esta especificación.")
            elif len(usuarios) == 1:
                computer_id = usuarios[0][0]

            if clave_nueva == clave_actual:
                if (cambios_no_clave(pantalla_actual, otros_actual, status_actual)
                        and len(usuarios) > 1 and not data["aplicar_a_todos"]):
                    conn.rollback()
                    return _conflicto_especificacion(
                        len(usuarios),
                        f"Cambiar pantalla/otros/estado se aplicará a los {len(usuarios)} equipos que comparten "
                        "esta especificación. Envíe aplicar_a_todos=true para confirmar.")
                cur.execute("""
                    UPDATE hardware_specs SET pantalla = %s, otros = %s, status_id = %s WHERE id = %s
                """, (nueva_pantalla, nuevos_otros, nuevo_status, id))
                conn.commit()
                return {"message": f"Hardware {id} actualizado correctamente", "hardware_id": id}

            if computer_id is None and usuarios:
                conn.rollback()
                return _conflicto_especificacion(
                    len(usuarios),
                    "Esta especificación la comparten varios equipos: indique numero_serie del equipo que se edita.")

            # ¿Ya existe una especificación idéntica a la nueva?
            cur.execute("""
                SELECT id, status_id, pantalla, otros FROM hardware_specs
                WHERE tipo_equipo = %s AND marca = %s AND modelo = %s AND procesador = %s
                  AND ram_gb = %s AND almacenamiento = %s AND sistema_operativo = %s
                  AND id <> %s
                FOR UPDATE
            """, clave_nueva + (id,))
            destino = cur.fetchone()

            if computer_id is None:
                # Especificación huérfana (ningún equipo la usa)
                if destino:
                    raise HTTPException(status_code=409, detail="Ya existe una especificación idéntica.")
                hardware_id = id
            elif len(usuarios) == 1 and not destino:
                hardware_id = id  # solo este equipo la usa: edición en sitio
            elif destino:
                hardware_id = destino[0]
                # Reutilizar una spec existente no puede descartar en silencio pantalla/otros/status enviados
                if cambios_no_clave(destino[2], destino[3], destino[1]):
                    n = _equipos_que_usan_spec(cur, hardware_id)
                    if n and not data["aplicar_a_todos"]:
                        conn.rollback()
                        return _conflicto_especificacion(
                            n, f"Ya existe una especificación idéntica con otra pantalla/otros/estado y la usan {n} "
                               "equipos. Envíe aplicar_a_todos=true para aplicarlos a todos.")
                    cur.execute("""
                        UPDATE hardware_specs SET pantalla = %s, otros = %s, status_id = %s WHERE id = %s
                    """, (data["pantalla"] if data["pantalla"] is not None else destino[2],
                          data["otros"] if data["otros"] is not None else destino[3],
                          data["status_id"] if data["status_id"] is not None else destino[1],
                          hardware_id))
                elif destino[1] == 7:  # estaba eliminada y no hay cambios explícitos: se reactiva
                    cur.execute("UPDATE hardware_specs SET status_id = %s WHERE id = %s", (nuevo_status, hardware_id))
            else:
                cur.execute("""
                    INSERT INTO hardware_specs
                    (tipo_equipo, marca, modelo, procesador, ram_gb, almacenamiento, sistema_operativo,
                     pantalla, otros, status_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tipo_equipo, marca, modelo, procesador, ram_gb, almacenamiento, sistema_operativo)
                    DO NOTHING
                    RETURNING id
                """, clave_nueva + (nueva_pantalla, nuevos_otros, nuevo_status))
                nueva = cur.fetchone()
                if nueva:
                    hardware_id = nueva[0]
                else:  # otra transacción la creó entre medio
                    cur.execute("""
                        SELECT id FROM hardware_specs
                        WHERE tipo_equipo = %s AND marca = %s AND modelo = %s AND procesador = %s
                          AND ram_gb = %s AND almacenamiento = %s AND sistema_operativo = %s
                    """, clave_nueva)
                    hardware_id = cur.fetchone()[0]

            if hardware_id == id:
                cur.execute("""
                    UPDATE hardware_specs
                    SET tipo_equipo = %s, marca = %s, modelo = %s, procesador = %s, ram_gb = %s,
                        almacenamiento = %s, sistema_operativo = %s, pantalla = %s, otros = %s, status_id = %s
                    WHERE id = %s
                """, clave_nueva + (nueva_pantalla, nuevos_otros, nuevo_status, id))
            elif computer_id is not None:
                cur.execute("UPDATE computers SET hardware_spec_id = %s WHERE id = %s", (hardware_id, computer_id))

            conn.commit()
            return {"message": f"Hardware {id} actualizado correctamente", "hardware_id": hardware_id}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("Error en PUT /equipos/hardware/{id}")
            raise HTTPException(status_code=500, detail="Error al actualizar hardware.")
