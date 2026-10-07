"""Pruebas funcionales de la API (ver conftest.py: solo corren contra una copia local)."""
from datetime import date, timedelta

import pytest

from conftest import KEVIN_ID, KEVIN_CEDULA


# =========================
# HELPERS
# =========================
def crear_computadora(client, serie, anio=2023, spec=None):
    spec = spec or {
        "tipo_equipo": "Laptop", "marca": "TESTMARCA", "modelo": f"MODELO-{serie}",
        "procesador": "TEST CPU", "ram_gb": 16, "almacenamiento": "512GB",
        "sistema_operativo": "Windows 11", "pantalla": "", "otros": "", "status_id": 5,
    }
    hw = client.post("/equipos/hardware", json=spec)
    assert hw.status_code == 200, hw.text
    pc = client.post("/equipos/computers", json={
        "hardware_spec_id": hw.json()["hardware_id"],
        "numero_serie": serie,
        "tipo_propiedad": "PROPIO",
        "tarifa_mensual": 0,
        "fecha_recepcion_proveedor": date.today().isoformat(),
        "anio_fabricacion": anio,
    })
    assert pc.status_code == 200, pc.text
    return hw.json()["hardware_id"], pc.json()["computer_id"]


def buscar_en_inventario(client, serie):
    inv = client.get("/equipos/vista/inventario-general").json()
    return next((e for e in inv if e["numero_serie"] == serie), None)


def estado_computadora(db, computer_id):
    db.execute("SELECT s.nombre FROM computers c LEFT JOIN statuses s ON s.id = c.estado_id WHERE c.id = %s",
               (computer_id,))
    return db.fetchone()[0]


def computadora_de_kevin(db):
    db.execute("SELECT computer_id FROM computer_assignments WHERE person_id = %s AND activo", (KEVIN_ID,))
    fila = db.fetchone()
    return fila[0] if fila else None


def accesorios_de_kevin(db):
    db.execute("SELECT accessory_id FROM person_accessories WHERE person_id = %s AND activo ORDER BY 1",
               (KEVIN_ID,))
    return [f[0] for f in db.fetchall()]


# =========================
# CONSULTAS (todas las pantallas)
# =========================
@pytest.mark.parametrize("ruta", [
    "/equipos/catalogos/statuses",
    "/equipos/companies",
    "/equipos/people",
    "/equipos/hardware",
    "/equipos/accessory-types",
    "/equipos/accessories/disponibles",
    "/equipos/computers/disponibles",
    "/equipos/vista/inventario-general",
    "/equipos/vista/computadora-asignada",
    "/equipos/vista/equipo-completo",
    f"/equipos/vista/equipo-completo/{KEVIN_CEDULA}",
    f"/equipos/vista/accesorios-por-persona/{KEVIN_CEDULA}",
    f"/equipos/accesorios/persona/{KEVIN_CEDULA}",
    "/mantenimiento",
    "/mantenimiento/computadoras",
])
def test_consultas_responden(client, ruta):
    r = client.get(ruta)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_inventario_incluye_anio_fabricacion(client):
    inv = client.get("/equipos/vista/inventario-general").json()
    assert inv, "El inventario no debería estar vacío"
    assert all("anio_fabricacion" in e for e in inv)
    assert any(e["anio_fabricacion"] for e in inv)


def test_kevin_existe_y_tiene_accesorios(client):
    personas = client.get("/equipos/people").json()
    kevin = next(p for p in personas if p["id"] == KEVIN_ID)
    assert kevin["cedula"] == KEVIN_CEDULA
    accs = client.get(f"/equipos/accesorios/persona/{KEVIN_CEDULA}").json()
    assert all(a["cedula"] == KEVIN_CEDULA for a in accs)


# =========================
# LOGIN
# =========================
def test_login_credenciales_invalidas(client):
    r = client.post("/auth/login", json={"username": "no-existe", "password": "x"})
    assert r.status_code in (400, 401)


def test_registro_y_login_usuario_prueba(client, serie_unica):
    usuario = serie_unica.lower()
    r = client.post("/auth/register", json={"username": usuario, "password": "clave-prueba", "role": "USER"})
    assert r.status_code == 200, r.text
    assert client.post("/auth/register", json={"username": usuario, "password": "otra-clave-prueba", "role": "USER"}).status_code == 400
    ok = client.post("/auth/login", json={"username": usuario, "password": "clave-prueba"})
    assert ok.status_code == 200, ok.text
    mal = client.post("/auth/login", json={"username": usuario, "password": "otra"})
    assert mal.status_code in (400, 401)


# =========================
# EQUIPOS
# =========================
def test_crear_equipo_aparece_con_anio(client, serie_unica):
    _, pc_id = crear_computadora(client, serie_unica, anio=2021)
    fila = buscar_en_inventario(client, serie_unica)
    assert fila is not None
    assert fila["anio_fabricacion"] == 2021
    assert fila["estado_computadora"] == "DISPONIBLE"
    disponibles = client.get("/equipos/computers/disponibles").json()
    assert any(c["id"] == pc_id for c in disponibles)


def test_serie_duplicada_rechazada(client, serie_unica):
    crear_computadora(client, serie_unica)
    hw = client.get("/equipos/hardware").json()[0]["id"]
    r = client.post("/equipos/computers", json={
        "hardware_spec_id": hw, "numero_serie": serie_unica, "tipo_propiedad": "PROPIO",
        "tarifa_mensual": 0, "fecha_recepcion_proveedor": date.today().isoformat(), "anio_fabricacion": 2020,
    })
    assert r.status_code == 400


def test_hardware_inexistente_rechazado(client, serie_unica):
    r = client.post("/equipos/computers", json={
        "hardware_spec_id": 99999999, "numero_serie": serie_unica, "tipo_propiedad": "PROPIO",
        "tarifa_mensual": 0, "fecha_recepcion_proveedor": date.today().isoformat(), "anio_fabricacion": 2020,
    })
    assert r.status_code == 400


def test_baja_equipo(client, db, serie_unica):
    _, pc_id = crear_computadora(client, serie_unica)
    r = client.put(f"/equipos/computers/{serie_unica}/status", json={"nuevo_estado": "BAJA"})
    assert r.status_code == 200, r.text
    assert estado_computadora(db, pc_id) == "BAJA"
    assert not any(c["id"] == pc_id for c in client.get("/equipos/computers/disponibles").json())


def test_cambio_estado_equipo_inexistente(client):
    r = client.put("/equipos/computers/NO-EXISTE-XYZ/status", json={"nuevo_estado": "BAJA"})
    assert r.status_code == 404


def test_eliminar_y_reactivar_equipo(client, db, serie_unica):
    _, pc_id = crear_computadora(client, serie_unica)
    assert client.delete(f"/equipos/computers/{serie_unica}").status_code == 200
    assert estado_computadora(db, pc_id) == "ELIMINADO"
    # Ya no aparece en mantenimiento
    assert not any(c["id"] == pc_id for c in client.get("/mantenimiento/computadoras").json())
    # Registrar de nuevo la misma serie la reactiva
    hw = client.get("/equipos/hardware").json()[0]["id"]
    r = client.post("/equipos/computers", json={
        "hardware_spec_id": hw, "numero_serie": serie_unica, "tipo_propiedad": "ARRIENDO",
        "tarifa_mensual": 10, "fecha_recepcion_proveedor": date.today().isoformat(), "anio_fabricacion": 2019,
    })
    assert r.status_code == 200 and r.json()["computer_id"] == pc_id
    assert estado_computadora(db, pc_id) == "DISPONIBLE"


def test_eliminar_equipo_inexistente(client):
    assert client.delete("/equipos/computers/NO-EXISTE-XYZ").status_code == 404


def test_editar_hardware(client, db, serie_unica):
    hw_id, _ = crear_computadora(client, serie_unica)
    r = client.put(f"/equipos/hardware/{hw_id}", json={
        "tipo_equipo": "Laptop", "marca": "TESTMARCA", "modelo": f"EDITADO-{serie_unica}", "procesador": "CPU2",
        "ram_gb": 32, "almacenamiento": "1TB", "sistema_operativo": "Windows 11",
        "pantalla": "14", "otros": "", "status_id": 5,
    })
    assert r.status_code == 200, r.text
    fila = buscar_en_inventario(client, serie_unica)
    assert fila["modelo"] == f"EDITADO-{serie_unica}" and fila["ram_gb"] == 32
    assert client.put("/equipos/hardware/99999999", json={
        "tipo_equipo": "x", "marca": "x", "modelo": "x", "procesador": "x", "ram_gb": 1,
        "almacenamiento": "x", "sistema_operativo": "x", "status_id": 5,
    }).status_code == 404


# =========================
# PERSONAS
# =========================
def test_crear_y_editar_persona(client, db, serie_unica):
    cedula = serie_unica[-10:]
    compania = client.get("/equipos/companies").json()[0]["id"]
    r = client.post("/equipos/people", json={
        "cedula": cedula, "nombre": "PERSONA DE PRUEBA", "cargo": "QA", "area": "TI",
        "email": "qa@example.com", "company_id": compania,
    })
    assert r.status_code == 200, r.text
    pid = r.json()["person_id"]
    assert any(p["id"] == pid for p in client.get("/equipos/people").json())

    r = client.put(f"/equipos/people/{pid}", json={
        "cedula": cedula, "nombre": "PERSONA EDITADA", "cargo": "QA", "area": "TI",
        "email": "qa@example.com", "company_id": compania, "status_id": 5,
    })
    assert r.status_code == 200, r.text
    db.execute("SELECT nombre FROM people WHERE id = %s", (pid,))
    assert db.fetchone()[0] == "PERSONA EDITADA"


def test_cedula_duplicada_rechazada(client):
    compania = client.get("/equipos/companies").json()[0]["id"]
    r = client.post("/equipos/people", json={
        "cedula": KEVIN_CEDULA, "nombre": "DUPLICADO", "cargo": "", "area": "", "email": "", "company_id": compania,
    })
    assert r.status_code >= 400


def test_editar_kevin_y_restaurar(client, db):
    kevin = next(p for p in client.get("/equipos/people").json() if p["id"] == KEVIN_ID)
    original = {k: kevin[k] for k in ("cedula", "nombre", "cargo", "area", "email", "company_id", "status_id")}
    try:
        r = client.put(f"/equipos/people/{KEVIN_ID}", json={**original, "cargo": "CARGO DE PRUEBA"})
        assert r.status_code == 200, r.text
        db.execute("SELECT cargo FROM people WHERE id = %s", (KEVIN_ID,))
        assert db.fetchone()[0] == "CARGO DE PRUEBA"
    finally:
        client.put(f"/equipos/people/{KEVIN_ID}", json=original)
    db.execute("SELECT cargo FROM people WHERE id = %s", (KEVIN_ID,))
    assert db.fetchone()[0] == original["cargo"]


def test_editar_persona_inexistente(client):
    r = client.put("/equipos/people/99999999", json={
        "cedula": "x", "nombre": "x", "cargo": "x", "area": "x", "email": "x", "company_id": 1, "status_id": 5,
    })
    assert r.status_code == 404


# =========================
# ACCESORIOS
# =========================
def test_tipo_accesorio_crear_y_duplicado(client, serie_unica):
    nombre = f"TIPO {serie_unica}"[:50]
    r = client.post("/equipos/accessory-types", json={"nombre": nombre})
    assert r.status_code == 200, r.text
    assert client.post("/equipos/accessory-types", json={"nombre": nombre}).status_code == 400
    assert client.post("/equipos/accessory-types", json={"nombre": "  "}).status_code == 400


def test_accesorio_crear_validar_eliminar(client, db, serie_unica):
    tipo = client.get("/equipos/accessory-types").json()[0]
    base = {"accessory_type_id": tipo["id"], "marca": "Logi", "modelo": "M1",
            "numero_serie": serie_unica, "tipo_propiedad": "propio"}
    r = client.post("/equipos/accessories", json=base)
    assert r.status_code == 200, r.text
    acc_id = r.json()["accessory_id"]
    disp = client.get("/equipos/accessories/disponibles").json()
    fila = next(a for a in disp if a["id"] == acc_id)
    assert fila["marca"] == "LOGI" and fila["tipo_propiedad"] == "PROPIO"

    assert client.post("/equipos/accessories", json=base).status_code == 400
    assert client.post("/equipos/accessories", json={**base, "numero_serie": "OTRA-" + serie_unica,
                                                     "tipo_propiedad": "PRESTADO"}).status_code == 400
    assert client.post("/equipos/accessories", json={**base, "numero_serie": "OTRA2-" + serie_unica,
                                                     "accessory_type_id": 99999999}).status_code == 400
    assert client.post("/equipos/accessories", json={**base, "marca": ""}).status_code == 400

    assert client.delete(f"/equipos/accessories/{acc_id}").status_code == 200
    assert not any(a["id"] == acc_id for a in client.get("/equipos/accessories/disponibles").json())
    # Volver a registrar la serie reactiva el accesorio
    r = client.post("/equipos/accessories", json=base)
    assert r.status_code == 200 and r.json()["accessory_id"] == acc_id


# =========================
# ASIGNACIONES (con el usuario Kevin Fajardo)
# =========================
def test_kevin_no_puede_tener_dos_computadoras(client, db, serie_unica):
    assert computadora_de_kevin(db) is not None, "Kevin debería tener equipo en la copia"
    _, pc_id = crear_computadora(client, serie_unica)
    r = client.post("/equipos/assign/computer", json={"computer_id": pc_id, "person_id": KEVIN_ID})
    assert r.status_code == 400
    assert "ya tiene" in r.json()["detail"]


def test_ciclo_completo_asignacion_kevin(client, db):
    pc_original = computadora_de_kevin(db)
    accs_originales = accesorios_de_kevin(db)
    assert pc_original and accs_originales

    # 1. Liberar todo lo de Kevin (botón LIBERAR de Equipos)
    r = client.post(f"/equipos/unassign/full/{KEVIN_ID}")
    assert r.status_code == 200, r.text
    assert computadora_de_kevin(db) is None
    assert accesorios_de_kevin(db) == []
    assert estado_computadora(db, pc_original) == "DISPONIBLE"
    assert client.get(f"/equipos/accesorios/persona/{KEVIN_CEDULA}").json() == []
    assert any(c["id"] == pc_original for c in client.get("/equipos/computers/disponibles").json())

    # 2. Reasignar la misma computadora (pantalla Asignaciones)
    r = client.post("/equipos/assign/computer", json={"computer_id": pc_original, "person_id": KEVIN_ID})
    assert r.status_code == 200, r.text
    assert estado_computadora(db, pc_original) == "ASIGNADO"
    fila = next(e for e in client.get("/equipos/vista/inventario-general").json() if e["id"] == pc_original)
    assert fila["person_id"] == KEVIN_ID

    # La misma computadora no se puede asignar dos veces
    r = client.post("/equipos/assign/computer", json={"computer_id": pc_original, "person_id": KEVIN_ID})
    assert r.status_code == 400

    # 3. Reasignar los accesorios
    for acc in accs_originales:
        r = client.post("/equipos/assign/accessory", json={"accessory_id": acc, "person_id": KEVIN_ID})
        assert r.status_code == 200, r.text
    assert accesorios_de_kevin(db) == accs_originales
    r = client.post("/equipos/assign/accessory", json={"accessory_id": accs_originales[0], "person_id": KEVIN_ID})
    assert r.status_code == 400

    # 4. Liberar un solo accesorio (Dashboard > Ver accesorios > LIBERAR) y devolverlo
    acc = accs_originales[0]
    assert client.put(f"/equipos/unassign/accessory/{acc}").status_code == 200
    assert acc not in accesorios_de_kevin(db)
    assert client.put(f"/equipos/unassign/accessory/{acc}").status_code == 404
    assert client.post("/equipos/assign/accessory", json={"accessory_id": acc, "person_id": KEVIN_ID}).status_code == 200
    assert accesorios_de_kevin(db) == accs_originales

    # 5. Liberar solo la computadora y devolverla
    assert client.put(f"/equipos/unassign/computer/{pc_original}").status_code == 200
    assert computadora_de_kevin(db) is None
    assert client.post("/equipos/assign/computer",
                       json={"computer_id": pc_original, "person_id": KEVIN_ID}).status_code == 200
    assert computadora_de_kevin(db) == pc_original


def test_baja_cierra_asignacion_activa(client, db, serie_unica):
    compania = client.get("/equipos/companies").json()[0]["id"]
    persona = client.post("/equipos/people", json={
        "cedula": serie_unica[-10:], "nombre": "PRUEBA BAJA", "cargo": "", "area": "", "email": "",
        "company_id": compania,
    }).json()["person_id"]
    _, pc_id = crear_computadora(client, serie_unica)
    assert client.post("/equipos/assign/computer", json={"computer_id": pc_id, "person_id": persona}).status_code == 200
    assert client.put(f"/equipos/computers/{serie_unica}/status", json={"nuevo_estado": "BAJA"}).status_code == 200
    db.execute("SELECT count(*) FROM computer_assignments WHERE computer_id = %s AND activo", (pc_id,))
    assert db.fetchone()[0] == 0


# =========================
# MANTENIMIENTO (sobre la computadora de Kevin)
# =========================
def test_mantenimiento_crud_completo(client, db, usuarios_sesion):
    admin = usuarios_sesion["ADMIN"][1]
    pc = computadora_de_kevin(db)
    assert pc
    hoy = date.today().isoformat()

    r = client.post("/mantenimiento", json={
        "computer_id": pc, "tipo_mantenimiento": "preventivo", "descripcion": "Limpieza interna",
        "tecnico": "ramos mantilla walter ricardo", "costo": "15.50", "usuario_registro": "falsificado",
        "fecha_mantenimiento": hoy,
    })
    assert r.status_code == 200, r.text
    mid = r.json()["maintenance_id"]

    hist = client.get(f"/mantenimiento/computadoras/{pc}").json()
    reg = next(m for m in hist if m["id"] == mid)
    assert reg["tipo_mantenimiento"] == "PREVENTIVO"
    assert reg["tecnico"] == "RAMOS MANTILLA WALTER RICARDO"
    assert float(reg["costo"]) == 15.5
    assert reg["usuario_registro"] == admin  # el campo usuario_registro del cuerpo se ignora

    fila = next(c for c in client.get("/mantenimiento/computadoras").json() if c["id"] == pc)
    assert fila["total_mantenimientos"] >= 1
    assert str(fila["ultimo_mantenimiento"]) == hoy
    assert fila["usuario_actual"] is not None

    general = client.get("/mantenimiento").json()
    assert any(m["id"] == mid and m["computer_id"] == pc and m["numero_serie"] for m in general)

    ayer = (date.today() - timedelta(days=1)).isoformat()
    r = client.put(f"/mantenimiento/{mid}", json={
        "tipo_mantenimiento": "CORRECTIVO", "descripcion": "Cambio de disco", "tecnico": "",
        "costo": "", "fecha_mantenimiento": ayer,
    })
    assert r.status_code == 200, r.text
    reg = next(m for m in client.get(f"/mantenimiento/computadoras/{pc}").json() if m["id"] == mid)
    assert reg["tipo_mantenimiento"] == "CORRECTIVO"
    assert reg["tecnico"] is None and reg["costo"] is None
    assert str(reg["fecha_mantenimiento"]) == ayer
    assert reg["usuario_registro"] == admin, "Editar no debe cambiar quién registró"

    assert client.delete(f"/mantenimiento/{mid}").status_code == 200
    assert not any(m["id"] == mid for m in client.get(f"/mantenimiento/computadoras/{pc}").json())
    assert client.delete(f"/mantenimiento/{mid}").status_code == 404


def test_mantenimiento_fecha_por_defecto_hoy(client, db, usuarios_sesion):
    pc = computadora_de_kevin(db)
    r = client.post("/mantenimiento", json={"computer_id": pc, "tipo_mantenimiento": "PREVENTIVO",
                                            "descripcion": "Sin fecha"})
    assert r.status_code == 200, r.text
    mid = r.json()["maintenance_id"]
    reg = next(m for m in client.get(f"/mantenimiento/computadoras/{pc}").json() if m["id"] == mid)
    assert str(reg["fecha_mantenimiento"]) == date.today().isoformat()
    assert reg["usuario_registro"] == usuarios_sesion["ADMIN"][1]
    client.delete(f"/mantenimiento/{mid}")


@pytest.mark.parametrize("cambios, mensaje", [
    ({"tipo_mantenimiento": "OTRO"}, "PREVENTIVO o CORRECTIVO"),
    ({"tipo_mantenimiento": ""}, "obligatorio"),
    ({"descripcion": "   "}, "obligatorio"),
    ({"fecha_mantenimiento": (date.today() + timedelta(days=1)).isoformat()}, "futura"),
    ({"fecha_mantenimiento": "31/12/2024"}, "no es valida"),
    ({"costo": "-1"}, "negativo"),
    ({"costo": "abc"}, "numero valido"),
    ({"computer_id": "abc"}, "numero valido"),
])
def test_mantenimiento_validaciones(client, db, cambios, mensaje):
    pc = computadora_de_kevin(db)
    base = {"computer_id": pc, "tipo_mantenimiento": "PREVENTIVO", "descripcion": "x"}
    db.execute("SELECT count(*) FROM computer_maintenance")
    antes = db.fetchone()[0]
    r = client.post("/mantenimiento", json={**base, **cambios})
    assert r.status_code == 400, r.text
    assert mensaje in r.json()["detail"]
    db.execute("SELECT count(*) FROM computer_maintenance")
    assert db.fetchone()[0] == antes


def test_mantenimiento_equipo_inexistente_o_eliminado(client, serie_unica):
    base = {"tipo_mantenimiento": "PREVENTIVO", "descripcion": "x"}
    assert client.post("/mantenimiento", json={**base, "computer_id": 99999999}).status_code == 404
    _, pc_id = crear_computadora(client, serie_unica)
    client.delete(f"/equipos/computers/{serie_unica}")
    assert client.post("/mantenimiento", json={**base, "computer_id": pc_id}).status_code == 404


def test_mantenimiento_editar_inexistente(client):
    r = client.put("/mantenimiento/99999999", json={"tipo_mantenimiento": "PREVENTIVO", "descripcion": "x"})
    assert r.status_code == 404
    r = client.put("/mantenimiento/99999999", json={"tipo_mantenimiento": "X", "descripcion": "x"})
    assert r.status_code == 400


def test_mantenimiento_cors_puerto_3001(client):
    r = client.options("/mantenimiento/1", headers={
        "Origin": "http://localhost:3001", "Access-Control-Request-Method": "PUT",
    })
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3001"


# =========================
# ANTIGUOS ERRORES CONOCIDOS (corregidos; antes xfail)
# =========================
def _crear_persona(client, cedula, nombre="PRUEBA"):
    compania = client.get("/equipos/companies").json()[0]["id"]
    r = client.post("/equipos/people", json={
        "cedula": cedula, "nombre": nombre, "cargo": "", "area": "", "email": "", "company_id": compania,
    })
    assert r.status_code == 200, r.text
    return r.json()["person_id"]


def test_eliminar_persona(client, serie_unica):
    pid = _crear_persona(client, serie_unica[-10:], "BORRAR")
    assert any(p["id"] == pid for p in client.get("/equipos/people").json())
    assert client.delete(f"/equipos/people/{pid}").status_code == 200
    assert not any(p["id"] == pid for p in client.get("/equipos/people").json())
    assert client.delete(f"/equipos/people/{pid}").status_code == 404


def test_eliminar_persona_inexistente_404(client):
    assert client.delete("/equipos/people/99999999").status_code == 404


def test_eliminar_persona_con_asignaciones_409(client, serie_unica):
    pid = _crear_persona(client, serie_unica[-10:])
    _, pc_id = crear_computadora(client, serie_unica)
    assert client.post("/equipos/assign/computer", json={"computer_id": pc_id, "person_id": pid}).status_code == 200
    assert client.delete(f"/equipos/people/{pid}").status_code == 409
    client.post(f"/equipos/unassign/full/{pid}")
    assert client.delete(f"/equipos/people/{pid}").status_code == 200


def test_recrear_persona_eliminada_la_reactiva(client, serie_unica):
    cedula = serie_unica[-10:]
    pid = _crear_persona(client, cedula, "PRIMERA")
    assert client.delete(f"/equipos/people/{pid}").status_code == 200
    assert _crear_persona(client, cedula, "SEGUNDA") == pid
    assert client.post("/equipos/people", json={
        "cedula": cedula, "nombre": "X", "company_id": client.get("/equipos/companies").json()[0]["id"],
    }).status_code == 400  # ya activa: cédula duplicada


def test_editar_equipo_no_cambia_otros_equipos(client, serie_unica):
    spec = {"tipo_equipo": "Laptop", "marca": "COMPARTIDA", "modelo": f"M-{serie_unica}", "procesador": "CPU",
            "ram_gb": 8, "almacenamiento": "256GB", "sistema_operativo": "Windows 11", "status_id": 5}
    hw_a, _ = crear_computadora(client, serie_unica + "A", spec=spec)
    hw_b, _ = crear_computadora(client, serie_unica + "B", spec=spec)
    assert hw_a == hw_b  # el backend reutiliza la misma especificación
    # Compartida y sin indicar el equipo: no se adivina
    assert client.put(f"/equipos/hardware/{hw_a}", json={**spec, "ram_gb": 64}).status_code == 409
    assert buscar_en_inventario(client, serie_unica + "B")["ram_gb"] == 8
    r = client.put(f"/equipos/hardware/{hw_a}", json={**spec, "ram_gb": 64, "numero_serie": serie_unica + "A"})
    assert r.status_code == 200, r.text
    assert r.json()["hardware_id"] != hw_a
    assert buscar_en_inventario(client, serie_unica + "A")["ram_gb"] == 64
    assert buscar_en_inventario(client, serie_unica + "B")["ram_gb"] == 8


def test_editar_equipo_con_spec_propia_edita_en_sitio(client, serie_unica):
    spec = {"tipo_equipo": "Laptop", "marca": "TESTMARCA", "modelo": f"P-{serie_unica}", "procesador": "CPU",
            "ram_gb": 8, "almacenamiento": "256GB", "sistema_operativo": "Windows 11", "status_id": 5}
    hw, _ = crear_computadora(client, serie_unica, spec=spec)
    r = client.put(f"/equipos/hardware/{hw}", json={**spec, "ram_gb": 32})
    assert r.status_code == 200 and r.json()["hardware_id"] == hw
    assert buscar_en_inventario(client, serie_unica)["ram_gb"] == 32


def test_estado_invalido_se_rechaza(client, serie_unica):
    crear_computadora(client, serie_unica)
    r = client.put(f"/equipos/computers/{serie_unica}/status", json={"nuevo_estado": "INVENTADO"})
    assert r.status_code == 400
    assert buscar_en_inventario(client, serie_unica) is not None


def test_devolucion_no_se_duplica_en_historial(client, db, serie_unica, usuarios_sesion):
    pid = _crear_persona(client, serie_unica[-10:], "PRUEBA HIST")
    _, pc_id = crear_computadora(client, serie_unica)
    client.post("/equipos/assign/computer", json={"computer_id": pc_id, "person_id": pid})
    client.post(f"/equipos/unassign/full/{pid}")
    db.execute("SELECT usuario_registro FROM delivery_history WHERE computer_id = %s AND tipo_movimiento = 'DEVOLUCION'",
               (pc_id,))
    filas = db.fetchall()
    assert len(filas) == 1
    assert filas[0][0] == usuarios_sesion["ADMIN"][1]  # autoría = usuario autenticado, no 'sistema'


def test_eliminar_accesorio_inexistente_404(client):
    assert client.delete("/equipos/accessories/99999999").status_code == 404


def test_persona_campos_faltantes_da_422(client):
    assert client.post("/equipos/people", json={"nombre": "SIN CEDULA"}).status_code == 422


def test_editar_hardware_a_specs_existentes_reutiliza_la_existente(client, serie_unica):
    base = {"tipo_equipo": "Laptop", "marca": "TESTMARCA", "procesador": "CPU", "ram_gb": 8,
            "almacenamiento": "256GB", "sistema_operativo": "Windows 11", "status_id": 5}
    hw_a, _ = crear_computadora(client, serie_unica + "A", spec={**base, "modelo": f"A-{serie_unica}"})
    hw_b, _ = crear_computadora(client, serie_unica + "B", spec={**base, "modelo": f"B-{serie_unica}"})
    r = client.put(f"/equipos/hardware/{hw_a}", json={**base, "modelo": f"B-{serie_unica}"})
    assert r.status_code == 200, r.text
    assert r.json()["hardware_id"] == hw_b
    assert buscar_en_inventario(client, serie_unica + "A")["modelo"] == f"B-{serie_unica}"
