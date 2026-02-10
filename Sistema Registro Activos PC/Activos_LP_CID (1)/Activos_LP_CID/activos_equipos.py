from fastapi import APIRouter, HTTPException
from psycopg2.extras import RealDictCursor
from datetime import date
import psycopg2, os
 
router = APIRouter(prefix="/equipos", tags=["Equipos"])
 
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
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO companies (nombre,status_id)
            VALUES (%s,(SELECT id FROM statuses WHERE nombre='ACTIVO'))
            RETURNING id
        """, (data["nombre"],))
        return {"company_id": cur.fetchone()[0]}
 
@router.post("/people")
def create_person(data: dict):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO people
            (cedula,nombre,cargo,area,email,company_id,status_id)
            VALUES (%s,%s,%s,%s,%s,%s,
                (SELECT id FROM statuses WHERE nombre='ACTIVO'))
            RETURNING id
        """, (
            data["cedula"], data["nombre"], data["cargo"],
            data["area"], data["email"], data["company_id"]
        ))
        return {"person_id": cur.fetchone()[0]}
 
@router.post("/hardware")
def create_hardware(data: dict):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO hardware_specs
            (tipo_equipo,marca,modelo,procesador,ram_gb,
             almacenamiento,sistema_operativo,status_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,
                (SELECT id FROM statuses WHERE nombre='ACTIVO'))
            RETURNING id
        """, (
            data["tipo_equipo"], data["marca"], data["modelo"],
            data["procesador"], data["ram_gb"],
            data["almacenamiento"], data["sistema_operativo"]
        ))
        return {"hardware_id": cur.fetchone()[0]}
 
@router.post("/computers")
def create_computer(data: dict):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO computers
                (hardware_spec_id,numero_serie,tipo_propiedad,
                 estado_id,tarifa_mensual,fecha_recepcion_proveedor,anio_fabricacion)
                VALUES (%s,%s,%s,
                    (SELECT id FROM statuses WHERE nombre='DISPONIBLE'),
                    %s,%s,%s)
                RETURNING id
            """, (
                data["hardware_spec_id"],
                data["numero_serie"],
                data["tipo_propiedad"],
                data["tarifa_mensual"],
                data["fecha_recepcion_proveedor"],
                data["anio_fabricacion"]
            ))
            return {"computer_id": cur.fetchone()[0]}
            
    except psycopg2.errors.UniqueViolation:
        # Esto captura el error de duplicados específicamente
        raise HTTPException(status_code=400, detail="El número de serie ya está registrado.")
    except Exception as e:
        # Esto captura cualquier otro error
        raise HTTPException(status_code=500, detail=str(e))
 
@router.post("/accessory-types")
def create_accessory_type(data: dict):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO accessory_types (nombre,status_id)
            VALUES (%s,(SELECT id FROM statuses WHERE nombre='ACTIVO'))
            RETURNING id
        """, (data["nombre"],))
        return {"accessory_type_id": cur.fetchone()[0]}
 
@router.post("/accessories")

def create_accessory(data: dict):

    with get_conn() as conn, conn.cursor() as cur:

        cur.execute("""

            INSERT INTO accessories

            (accessory_type_id, marca, modelo, numero_serie, estado_id, tipo_propiedad)

            VALUES (%s, %s, %s, %s,

                (SELECT id FROM statuses WHERE nombre = 'DISPONIBLE'),

                %s

            )

            RETURNING id

        """, (

            data["accessory_type_id"],

            data["marca"],

            data["modelo"],

            data["numero_serie"],

            data["tipo_propiedad"]   # 👈 nuevo campo

        ))

        return {"accessory_id": cur.fetchone()[0]}

 
 
# =========================
# ASIGNACIONES
# =========================
@router.post("/assign/computer")
def assign_computer(data: dict):
    with get_conn() as conn, conn.cursor() as cur:
        # 1. VALIDACIÓN CORREGIDA: Ahora aceptamos DISPONIBLE o NUEVO
        cur.execute("""
    SELECT 1 FROM computers c
    JOIN statuses s ON c.estado_id = s.id
    -- AQUÍ ESTÁ EL TRUCO: ACEPTAR 'NUEVO'
    WHERE c.id=%s AND s.nombre IN ('DISPONIBLE', 'NUEVO') 
""", (data["computer_id"],))
        
        if not cur.fetchone():
            raise HTTPException(400, "Computadora no disponible (Debe estar DISPONIBLE o NUEVO)")

        # 2. CREAR ASIGNACIÓN
        cur.execute("""
            INSERT INTO computer_assignments
            (computer_id, person_id, fecha_asignacion)
            VALUES (%s, %s, %s)
        """, (data["computer_id"], data["person_id"], date.today()))

        # 3. ACTUALIZAR ESTADO A 'ASIGNADO'
        cur.execute("""
            UPDATE computers
            SET estado_id=(SELECT id FROM statuses WHERE nombre='ASIGNADO')
            WHERE id=%s
        """, (data["computer_id"],))

        return {"message": "Computadora asignada exitosamente"}
    
@router.post("/assign/accessory")
def assign_accessory(data: dict):
    with get_conn() as conn, conn.cursor() as cur:
        # 1. VALIDAR: Aceptamos DISPONIBLE o NUEVO
        cur.execute("""
            SELECT 1 FROM accessories a
            JOIN statuses s ON a.estado_id = s.id
            WHERE a.id=%s AND s.nombre IN ('DISPONIBLE', 'NUEVO')
        """, (data["accessory_id"],))
        
        if not cur.fetchone():
            raise HTTPException(400, "Accesorio no disponible (Debe estar DISPONIBLE o NUEVO)")

        # 2. INSERTAR RELACIÓN
        cur.execute("""
            INSERT INTO person_accessories
            (person_id, accessory_id, fecha_asignacion)
            VALUES (%s, %s, %s)
        """, (data["person_id"], data["accessory_id"], date.today()))

        # 3. ACTUALIZAR ESTADO A 'ASIGNADO'
        cur.execute("""
            UPDATE accessories
            SET estado_id=(SELECT id FROM statuses WHERE nombre='ASIGNADO')
            WHERE id=%s
        """, (data["accessory_id"],))

        return {"message": "Accesorio asignado correctamente"}
 
# =========================
# DELETE = ELIMINADO
# =========================
# Busca esta parte en tu código y REEMPLÁZALA:
# @router.delete("/computers/{id}") ...

@router.delete("/computers/{serial}")
def delete_computer(serial: str):
    with get_conn() as conn, conn.cursor() as cur:
        # 1. Verificamos que el equipo exista antes de borrarlo
        cur.execute("SELECT id FROM computers WHERE numero_serie = %s", (serial,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Equipo no encontrado")

        # 2. Marcamos como ELIMINADO usando el número de serie
        cur.execute("""
            UPDATE computers
            SET estado_id=(SELECT id FROM statuses WHERE nombre='ELIMINADO')
            WHERE numero_serie=%s
        """, (serial,))
        
        return {"message": f"Computadora {serial} eliminada"}
 
@router.delete("/accessories/{id}")
def delete_accessory(id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE accessories
            SET estado_id=(SELECT id FROM statuses WHERE nombre='ELIMINADO')
            WHERE id=%s
        """, (id,))
        return {"message": "Accesorio eliminado"}
 
# =========================
# VISTAS
# =========================
@router.get("/vista/equipo-completo")
def vista_equipo_completo():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM vw_equipo_completo ORDER BY empleado")
        return cur.fetchall()
 
@router.get("/vista/equipo-completo/{cedula}")
def vista_equipo_por_cedula(cedula: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM vw_equipo_completo WHERE cedula=%s", (cedula,))
        return cur.fetchall()
 
@router.get("/vista/inventario-general")
def vista_inventario_general():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM vw_inventario_general")
        return cur.fetchall()
@router.get("/vista/computadora-asignada")
def computadoras_asignadas():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM vw_computadora_asignada")
        return cur.fetchall()
 
@router.get("/vista/accesorios-por-persona/{cedula}")
def accesorios_por_persona(cedula: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT *
            FROM vw_accesorios_por_persona
            WHERE cedula = %s
        """, (cedula,))
        return cur.fetchall()
 
#GET CONSULTAS API
 
@router.get("/catalogos/statuses")
def get_statuses():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, nombre
            FROM statuses
            WHERE nombre <> 'ELIMINADO'
            ORDER BY nombre
        """)
        return cur.fetchall()
 
@router.get("/companies")
def get_companies():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT c.id, c.nombre
            FROM companies c
            JOIN statuses s ON c.status_id = s.id
            WHERE s.nombre <> 'ELIMINADO'
            ORDER BY c.nombre
        """)
        return cur.fetchall()
 
@router.get("/people")
def get_people():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT p.id, p.cedula, p.nombre, p.company_id
            FROM people p
            JOIN statuses s ON p.status_id = s.id
            WHERE s.nombre = 'ACTIVO'
            ORDER BY p.nombre
        """)
        return cur.fetchall()
 
@router.get("/hardware")
def get_hardware():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, tipo_equipo, marca, modelo
            FROM hardware_specs
            WHERE status_id <> (SELECT id FROM statuses WHERE nombre='ELIMINADO')
            ORDER BY marca, modelo
        """)
        return cur.fetchall()
 
@router.get("/accessory-types")
def get_accessory_types():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT at.id, at.nombre
            FROM accessory_types at
            JOIN statuses s ON at.status_id = s.id
            WHERE s.nombre <> 'ELIMINADO'
            ORDER BY at.nombre
        """)
        return cur.fetchall()
 
@router.get("/accessories/disponibles")
def get_accessories_disponibles():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
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
            -- CAMBIO: Aceptamos DISPONIBLE y NUEVO
            WHERE s.nombre IN ('DISPONIBLE', 'NUEVO')
            ORDER BY at.nombre
        """)
        return cur.fetchall()
    
@router.get("/computers/disponibles")
def get_computers_disponibles():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
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
            -- CAMBIO: Ahora traemos DISPONIBLE y NUEVO
            WHERE s.nombre IN ('DISPONIBLE', 'NUEVO')
            ORDER BY c.numero_serie
        """)
        return cur.fetchall()
    
# Agrega esto debajo de tus otros endpoints, antes de los GET

@router.put("/computers/{serial}/status")
def change_computer_status(serial: str, data: dict):
    # data espera recibir: {"nuevo_estado": "DISPONIBLE"} o "BAJA"
    nuevo_estado = data.get("nuevo_estado")
    
    with get_conn() as conn, conn.cursor() as cur:
        # 1. Validar que el equipo exista
        cur.execute("SELECT id FROM computers WHERE numero_serie = %s", (serial,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Equipo no encontrado")

        # 2. Actualizar al estado deseado
        cur.execute("""
            UPDATE computers
            SET estado_id = (SELECT id FROM statuses WHERE nombre = %s)
            WHERE numero_serie = %s
        """, (nuevo_estado, serial))
        
        # 3. Si se está "LIBERANDO" (poniendo en DISPONIBLE), opcionalmente podrías querer 
        # registrar fecha de devolución en asignaciones, pero por ahora solo liberamos el activo.
        
        return {"message": f"Equipo {serial} actualizado a {nuevo_estado}"}
        
@router.get("/accesorios/persona/{cedula}")
def get_accesorios_persona(cedula: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT *
            FROM vw_accesorios_por_persona
            WHERE cedula = %s
        """, (cedula,))
        return cur.fetchall()
    

@router.post("/unassign/full/{person_id}")
def unassign_full(person_id: int):
 
    with get_conn() as conn, conn.cursor() as cur:
 
        # ======================
        # 1️⃣ Buscar computadora
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
 
            # Registrar historial DEVOLUCION COMPUTADORA
            cur.execute("""
                INSERT INTO delivery_history
                (computer_id, person_id, tipo_movimiento, fecha_movimiento, usuario_registro)
                VALUES (%s,%s,'DEVOLUCION',CURRENT_DATE,'sistema')
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
                    SELECT id FROM statuses WHERE nombre='DISPONIBLE'
                )
                WHERE id = %s
            """, (computer_id,))
 
        # ======================
        # 2️⃣ Accesorios
        # ======================
        cur.execute("""
            SELECT accessory_id
            FROM person_accessories
            WHERE person_id = %s
        """, (person_id,))
        accesorios = [a[0] for a in cur.fetchall()]
 
        for acc in accesorios:
 
            # Historial accesorio
            cur.execute("""
                INSERT INTO accessory_history
                (accessory_id, person_id, tipo_movimiento, fecha_movimiento, usuario_registro)
                VALUES (%s,%s,'DEVOLUCION',CURRENT_DATE,'sistema')
            """, (acc, person_id))
 
        # Eliminar relación
        cur.execute("""
            DELETE FROM person_accessories
            WHERE person_id = %s
        """, (person_id,))
 
        # Liberar accesorios
        if accesorios:
            cur.execute("""
                UPDATE accessories
                SET estado_id = (
                    SELECT id FROM statuses WHERE nombre='DISPONIBLE'
                )
                WHERE id = ANY(%s)
            """, (accesorios,))
 
        return {"mensaje": "Equipo completo desasignado"}