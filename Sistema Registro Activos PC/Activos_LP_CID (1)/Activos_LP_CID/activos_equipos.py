from fastapi import APIRouter, HTTPException
from psycopg2.extras import RealDictCursor
from datetime import date
import psycopg2
import os
import traceback


router = APIRouter(prefix="/equipos", tags=["Equipos"])


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


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


# =========================
# CREACIONES
# =========================
@router.post("/companies")
def create_company(data: dict):
    print("POST /equipos/companies payload:", data)
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
            print("=== ERROR EN /equipos/companies ===")
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al crear compañía: {str(e)}")


@router.post("/people")
def create_person(data: dict):
    print("POST /equipos/people payload:", data)
    with get_conn() as conn, conn.cursor() as cur:
        try:
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
        except Exception as e:
            conn.rollback()
            print("=== ERROR EN /equipos/people ===")
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al crear persona: {str(e)}")


@router.post("/hardware")
def create_hardware(data: dict):
    print("POST /equipos/hardware payload:", data)
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, status_id
                FROM hardware_specs
                WHERE tipo_equipo = %s
                  AND marca = %s
                  AND modelo = %s
                  AND procesador = %s
                  AND ram_gb = %s
                  AND almacenamiento = %s
                  AND sistema_operativo = %s
                LIMIT 1
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
                hardware_id, status_id = existing

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
                 ram_gb, almacenamiento, sistema_operativo, status_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 5)
                RETURNING id
            """, (
                data["tipo_equipo"],
                data["marca"],
                data["modelo"],
                data["procesador"],
                data["ram_gb"],
                data["almacenamiento"],
                data["sistema_operativo"]
            ))

            hardware_id = cur.fetchone()[0]
            conn.commit()

            return {
                "hardware_id": hardware_id,
                "message": "Hardware creado correctamente."
            }

    except Exception as e:
        print("=== ERROR EN /equipos/hardware ===")
        print("Payload recibido:", data)
        print("Tipo de error:", type(e).__name__)
        print("Mensaje:", str(e))
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/computers")
def create_computer(data: dict):
    print("POST /equipos/computers payload:", data)
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
        print("=== ERROR UNIQUE VIOLATION EN /equipos/computers ===")
        print("Payload recibido:", data)
        print("Tipo de error:", type(e).__name__)
        print("Mensaje:", str(e))
        traceback.print_exc()
        raise HTTPException(status_code=400, detail="El número de serie ya está registrado.")
    except Exception as e:
        print("=== ERROR EN /equipos/computers ===")
        print("Payload recibido:", data)
        print("Tipo de error:", type(e).__name__)
        print("Mensaje:", str(e))
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al crear computadora: {str(e)}")


@router.post("/accessory-types")
def create_accessory_type(data: dict):
    print("POST /equipos/accessory-types payload:", data)
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
            print("=== ERROR EN /equipos/accessory-types ===")
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al crear tipo de accesorio: {str(e)}")


@router.post("/accessories")
def create_accessory(data: dict):
    print("POST /equipos/accessories payload:", data)
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
            print("=== ERROR EN /equipos/accessories ===")
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al crear accesorio: {str(e)}")


# =========================
# ASIGNACIONES
# =========================
@router.post("/assign/computer")
def assign_computer(data: dict):
    print("POST /equipos/assign/computer payload:", data)
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
            print("=== ERROR EN /equipos/assign/computer ===")
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al asignar computadora: {str(e)}")


@router.post("/assign/accessory")
def assign_accessory(data: dict):
    print("POST /equipos/assign/accessory payload:", data)
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

            conn.commit()

            return {
                "message": "Accesorio asignado correctamente",
                "relation_id": relation_id
            }

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            print("=== ERROR EN /equipos/assign/accessory ===")
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al asignar accesorio: {str(e)}")


# =========================
# DELETE = ELIMINADO
# =========================
@router.delete("/computers/{serial}")
def delete_computer(serial: str):
    print(f"DELETE /equipos/computers/{serial}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                SELECT id
                FROM computers
                WHERE numero_serie = %s
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
            print("=== ERROR EN DELETE /equipos/computers/{serial} ===")
            print("Serial recibido:", serial)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al eliminar computadora: {str(e)}")


@router.delete("/accessories/{id}")
def delete_accessory(id: int):
    print(f"DELETE /equipos/accessories/{id}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # Cerrar asignación activa si existe
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

        except Exception as e:
            conn.rollback()
            print("=== ERROR EN DELETE /equipos/accessories/{id} ===")
            print("ID recibido:", id)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al eliminar accesorio: {str(e)}")


# =========================
# VISTAS
# =========================
@router.get("/vista/equipo-completo")
def vista_equipo_completo():
    print("GET /equipos/vista/equipo-completo")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("SELECT * FROM vw_equipo_completo ORDER BY empleado")
            return cur.fetchall()
        except Exception as e:
            print("=== ERROR EN GET /equipos/vista/equipo-completo ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al consultar vista equipo completo: {str(e)}")


@router.get("/vista/equipo-completo/{cedula}")
def vista_equipo_por_cedula(cedula: str):
    print(f"GET /equipos/vista/equipo-completo/{cedula}")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("SELECT * FROM vw_equipo_completo WHERE cedula = %s", (cedula,))
            return cur.fetchall()
        except Exception as e:
            print("=== ERROR EN GET /equipos/vista/equipo-completo/{cedula} ===")
            print("Cédula recibida:", cedula)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al consultar equipo por cédula: {str(e)}")

@router.get("/vista/inventario-general")
def vista_inventario_general():
    print("GET /equipos/vista/inventario-general")
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
            print("=== ERROR EN GET /equipos/vista/inventario-general ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al consultar inventario general: {str(e)}")


@router.get("/vista/computadora-asignada")
def computadoras_asignadas():
    print("GET /equipos/vista/computadora-asignada")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("SELECT * FROM vw_computadora_asignada")
            return cur.fetchall()
        except Exception as e:
            print("=== ERROR EN GET /equipos/vista/computadora-asignada ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al consultar computadoras asignadas: {str(e)}")


@router.get("/vista/accesorios-por-persona/{cedula}")
def accesorios_por_persona(cedula: str):
    print(f"GET /equipos/vista/accesorios-por-persona/{cedula}")
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
            print("=== ERROR EN GET /equipos/vista/accesorios-por-persona/{cedula} ===")
            print("Cédula recibida:", cedula)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al consultar accesorios por persona: {str(e)}")


# =========================
# GET CONSULTAS API
# =========================
@router.get("/catalogos/statuses")
def get_statuses():
    print("GET /equipos/catalogos/statuses")
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
            print("=== ERROR EN GET /equipos/catalogos/statuses ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al obtener statuses: {str(e)}")


@router.get("/companies")
def get_companies():
    print("GET /equipos/companies")
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
            print("=== ERROR EN GET /equipos/companies ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al obtener compañías: {str(e)}")


@router.get("/people")
def get_people():
    print("GET /equipos/people")
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
            print("=== ERROR EN GET /equipos/people ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al obtener personas: {str(e)}")


@router.get("/hardware")
def get_hardware():
    print("GET /equipos/hardware")
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
            print("=== ERROR EN GET /equipos/hardware ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al obtener hardware: {str(e)}")


@router.get("/accessory-types")
def get_accessory_types():
    print("GET /equipos/accessory-types")
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
            print("=== ERROR EN GET /equipos/accessory-types ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al obtener tipos de accesorio: {str(e)}")


@router.get("/accessories/disponibles")
def get_accessories_disponibles():
    print("GET /equipos/accessories/disponibles")
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
            print("=== ERROR EN GET /equipos/accessories/disponibles ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al obtener accesorios disponibles: {str(e)}")


@router.get("/computers/disponibles")
def get_computers_disponibles():
    print("GET /equipos/computers/disponibles")
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
            print("=== ERROR EN GET /equipos/computers/disponibles ===")
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al obtener computadoras disponibles: {str(e)}")


@router.put("/computers/{serial}/status")
def change_computer_status(serial: str, data: dict):
    print(f"PUT /equipos/computers/{serial}/status payload:", data)
    nuevo_estado = data.get("nuevo_estado")

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT id FROM computers WHERE numero_serie = %s", (serial,))
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Equipo no encontrado")

            computer_id = row[0]

            # Si se libera, cerrar asignación activa
            if nuevo_estado == "DISPONIBLE":
                cur.execute("""
                    UPDATE computer_assignments
                    SET activo = FALSE,
                        fecha_desasignacion = CURRENT_DATE
                    WHERE computer_id = %s
                      AND activo = TRUE
                """, (computer_id,))

            cur.execute("""
                UPDATE computers
                SET estado_id = (SELECT id FROM statuses WHERE nombre = %s)
                WHERE numero_serie = %s
            """, (nuevo_estado, serial))

            conn.commit()
            return {"message": f"Equipo {serial} actualizado a {nuevo_estado}"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            print("=== ERROR EN PUT /equipos/computers/{serial}/status ===")
            print("Serial recibido:", serial)
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al cambiar estado: {str(e)}")


@router.get("/accesorios/persona/{cedula}")
def get_accesorios_persona(cedula: str):
    print(f"GET /equipos/accesorios/persona/{cedula}")
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
            print("=== ERROR EN GET /equipos/accesorios/persona/{cedula} ===")
            print("Cédula recibida:", cedula)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al obtener accesorios de persona: {str(e)}")


@router.put("/unassign/accessory/{accessory_id}")
def unassign_accessory(accessory_id: int):
    print(f"PUT /equipos/unassign/accessory/{accessory_id}")
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
                VALUES (%s, %s, 'DEVOLUCION', CURRENT_DATE, 'sistema')
            """, (accessory_id, person_id))

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
            print("=== ERROR EN PUT /equipos/unassign/accessory/{accessory_id} ===")
            print("Accessory ID recibido:", accessory_id)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al liberar accesorio: {str(e)}")


@router.post("/unassign/full/{person_id}")
def unassign_full(person_id: int):
    print(f"POST /equipos/unassign/full/{person_id}")
    with get_conn() as conn, conn.cursor() as cur:
        try:
            # ======================
            # 1. Buscar computadora activa
            # ======================
            cur.execute("""
                SELECT computer_id
                FROM computer_assignments
                WHERE person_id = %s
                  AND activo = TRUE
            """, (person_id,))
            comp = cur.fetchone()

            if comp:
                computer_id = comp[0]

                # Historial devolución computadora
                cur.execute("""
                    INSERT INTO delivery_history
                    (computer_id, person_id, tipo_movimiento, fecha_movimiento, usuario_registro)
                    VALUES (%s, %s, 'DEVOLUCION', CURRENT_DATE, 'sistema')
                """, (computer_id, person_id))

                # Desasignar computadora
                cur.execute("""
                    UPDATE computer_assignments
                    SET activo = FALSE,
                        fecha_desasignacion = CURRENT_DATE
                    WHERE computer_id = %s
                      AND activo = TRUE
                """, (computer_id,))

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
                    VALUES (%s, %s, 'DEVOLUCION', CURRENT_DATE, 'sistema')
                """, (acc, person_id))

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

        except Exception as e:
            conn.rollback()
            print("=== ERROR EN POST /equipos/unassign/full/{person_id} ===")
            print("Person ID recibido:", person_id)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error en desasignación completa: {str(e)}")


@router.put("/unassign/computer/{computer_id}")
def unassign_computer(computer_id: int):
    print(f"PUT /equipos/unassign/computer/{computer_id}")
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
            print("=== ERROR EN PUT /equipos/unassign/computer/{computer_id} ===")
            print("Computer ID recibido:", computer_id)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al liberar computadora: {str(e)}")


# =========================
# UPDATES
# =========================
@router.put("/people/{id}")
def update_person(id: int, data: dict):
    print(f"PUT /equipos/people/{id} payload:", data)
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT id FROM people WHERE id = %s", (id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Persona no encontrada")

            cur.execute("""
                UPDATE people
                SET cedula = %s,
                    nombre = %s,
                    cargo = %s,
                    area = %s,
                    email = %s,
                    company_id = %s,
                    status_id = %s
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
        except Exception as e:
            conn.rollback()
            print("=== ERROR EN PUT /equipos/people/{id} ===")
            print("ID recibido:", id)
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al actualizar persona: {str(e)}")


@router.put("/hardware/{id}")
def update_hardware(id: int, data: dict):
    print(f"PUT /equipos/hardware/{id} payload:", data)
    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("SELECT id FROM hardware_specs WHERE id = %s", (id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Hardware no encontrado")

            cur.execute("""
                UPDATE hardware_specs
                SET tipo_equipo = %s,
                    marca = %s,
                    modelo = %s,
                    procesador = %s,
                    ram_gb = %s,
                    almacenamiento = %s,
                    sistema_operativo = %s,
                    pantalla = %s,
                    otros = %s,
                    status_id = %s
                WHERE id = %s
            """, (
                data["tipo_equipo"],
                data["marca"],
                data["modelo"],
                data["procesador"],
                data["ram_gb"],
                data["almacenamiento"],
                data["sistema_operativo"],
                data.get("pantalla"),
                data.get("otros"),
                data["status_id"],
                id
            ))

            conn.commit()
            return {"message": f"Hardware {id} actualizado correctamente"}

        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            print("=== ERROR EN PUT /equipos/hardware/{id} ===")
            print("ID recibido:", id)
            print("Payload recibido:", data)
            print("Tipo de error:", type(e).__name__)
            print("Mensaje:", str(e))
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error al actualizar hardware: {str(e)}")
