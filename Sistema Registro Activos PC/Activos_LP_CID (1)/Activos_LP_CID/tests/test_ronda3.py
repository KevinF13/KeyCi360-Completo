"""Tercera ronda: copy-on-write de campos no clave, carrera asignar/eliminar, transiciones de estado,
limitador por IP, devolución al eliminar accesorios, hardware con pantalla/otros y RENTADO."""
import threading
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

import login
from app import app
from test_api import crear_computadora, estado_computadora


def _spec(serie, **extra):
    return {"tipo_equipo": "Laptop", "marca": "R3MARCA", "modelo": f"R3-{serie}", "procesador": "CPU",
            "ram_gb": 8, "almacenamiento": "256GB", "sistema_operativo": "Windows 11", **extra}


def _fila_spec(db, hw_id):
    db.execute("SELECT pantalla, otros, status_id FROM hardware_specs WHERE id = %s", (hw_id,))
    return db.fetchone()


def _persona(client, serie):
    compania = client.get("/equipos/companies").json()[0]["id"]
    r = client.post("/equipos/people", json={"cedula": serie[-10:], "nombre": "PRUEBA R3", "company_id": compania})
    assert r.status_code == 200, r.text
    return r.json()["person_id"]


# ---------- R2-N1: crear hardware persiste pantalla/otros ----------
def test_crear_hardware_persiste_pantalla_y_otros_y_nace_activo(client, db, serie_unica):
    r = client.post("/equipos/hardware", json={**_spec(serie_unica), "pantalla": '15.6"', "otros": "Dock", "status_id": 1})
    assert r.status_code == 200, r.text
    assert _fila_spec(db, r.json()["hardware_id"]) == ('15.6"', "Dock", 5)  # status_id del formulario se ignora


def test_reutilizar_hardware_con_pantalla_distinta_no_descarta_en_silencio(client, db, serie_unica):
    spec = _spec(serie_unica, pantalla="14", otros="")
    hw, _ = crear_computadora(client, serie_unica + "A", spec=spec)
    crear_computadora(client, serie_unica + "B", spec=spec)
    r = client.post("/equipos/hardware", json={**spec, "pantalla": "17"})
    assert r.status_code == 409
    assert r.json()["equipos_afectados"] == 2 and "detail" in r.json()
    assert _fila_spec(db, hw)[0] == "14"
    # pantalla vacía no es un cambio; igual a la guardada tampoco
    assert client.post("/equipos/hardware", json={**spec, "pantalla": ""}).status_code == 200
    assert client.post("/equipos/hardware", json={**spec, "pantalla": "14"}).status_code == 200
    assert client.post("/equipos/hardware", json={**spec, "pantalla": "17", "aplicar_a_todos": True}).status_code == 200
    assert _fila_spec(db, hw)[0] == "17"


def test_reutilizar_hardware_sin_equipos_aplica_los_datos(client, db, serie_unica):
    r1 = client.post("/equipos/hardware", json={**_spec(serie_unica), "pantalla": "13"})
    r2 = client.post("/equipos/hardware", json={**_spec(serie_unica), "pantalla": "15"})
    assert r2.status_code == 200 and r2.json()["hardware_id"] == r1.json()["hardware_id"]
    assert _fila_spec(db, r1.json()["hardware_id"])[0] == "15"


# ---------- R2-H5: campos no clave en spec compartida ----------
def test_editar_pantalla_de_spec_compartida_exige_confirmacion(client, db, serie_unica):
    spec = _spec(serie_unica, pantalla="14", status_id=5)
    hw, _ = crear_computadora(client, serie_unica + "A", spec=spec)
    crear_computadora(client, serie_unica + "B", spec=spec)
    cuerpo = {**spec, "pantalla": "16", "numero_serie": serie_unica + "A"}
    r = client.put(f"/equipos/hardware/{hw}", json=cuerpo)
    assert r.status_code == 409 and r.json()["equipos_afectados"] == 2
    assert _fila_spec(db, hw)[0] == "14"
    r = client.put(f"/equipos/hardware/{hw}", json={**cuerpo, "aplicar_a_todos": True})
    assert r.status_code == 200, r.text
    assert _fila_spec(db, hw)[0] == "16"


def test_editar_status_de_spec_compartida_exige_confirmacion(client, db, serie_unica):
    spec = _spec(serie_unica, status_id=5)
    hw, _ = crear_computadora(client, serie_unica + "A", spec=spec)
    crear_computadora(client, serie_unica + "B", spec=spec)
    r = client.put(f"/equipos/hardware/{hw}", json={**spec, "status_id": 6, "numero_serie": serie_unica + "A"})
    assert r.status_code == 409 and _fila_spec(db, hw)[2] == 5


def test_editar_sin_cambios_no_clave_en_spec_compartida_no_pide_confirmacion(client, serie_unica):
    spec = _spec(serie_unica, pantalla="14", otros="", status_id=5)
    hw, _ = crear_computadora(client, serie_unica + "A", spec=spec)
    crear_computadora(client, serie_unica + "B", spec=spec)
    assert client.put(f"/equipos/hardware/{hw}", json={**spec, "numero_serie": serie_unica + "A"}).status_code == 200


def test_editar_reutilizando_spec_existente_con_otra_pantalla_pide_confirmacion(client, db, serie_unica):
    base = _spec(serie_unica, pantalla="", status_id=5)
    a = {**base, "modelo": f"A-{serie_unica}"}
    b = {**base, "modelo": f"B-{serie_unica}"}
    hw_a, _ = crear_computadora(client, serie_unica + "A", spec=a)
    hw_b, _ = crear_computadora(client, serie_unica + "B1", spec=b)
    crear_computadora(client, serie_unica + "B2", spec=b)
    cuerpo = {**b, "pantalla": "21", "numero_serie": serie_unica + "A"}
    r = client.put(f"/equipos/hardware/{hw_a}", json=cuerpo)
    assert r.status_code == 409 and r.json()["equipos_afectados"] == 2
    assert _fila_spec(db, hw_b)[0] == "" and _fila_spec(db, hw_a)[0] == ""
    r = client.put(f"/equipos/hardware/{hw_a}", json={**cuerpo, "aplicar_a_todos": True})
    assert r.status_code == 200 and r.json()["hardware_id"] == hw_b
    assert _fila_spec(db, hw_b)[0] == "21"


def test_editar_spec_compartida_sin_serie_da_409_con_equipos_afectados(client, serie_unica):
    spec = _spec(serie_unica, status_id=5)
    hw, _ = crear_computadora(client, serie_unica + "A", spec=spec)
    crear_computadora(client, serie_unica + "B", spec=spec)
    r = client.put(f"/equipos/hardware/{hw}", json={**spec, "ram_gb": 64})
    assert r.status_code == 409 and r.json()["equipos_afectados"] == 2


# ---------- R2-H6: carrera asignar / eliminar computadora ----------
def test_eliminar_y_asignar_concurrentes_no_dejan_asignacion_huerfana(client, db, serie_unica):
    for ronda in range(5):
        serie = f"{serie_unica}-{ronda}"
        pid = _persona(client, f"{serie_unica}{ronda}")
        _, pc = crear_computadora(client, serie)
        barrera = threading.Barrier(2)

        def asignar():
            c = TestClient(app)
            c.headers.update(client.headers)
            barrera.wait()
            c.post("/equipos/assign/computer", json={"computer_id": pc, "person_id": pid})

        def eliminar():
            c = TestClient(app)
            c.headers.update(client.headers)
            barrera.wait()
            c.delete(f"/equipos/computers/{serie}")

        hilos = [threading.Thread(target=asignar), threading.Thread(target=eliminar)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        assert estado_computadora(db, pc) == "ELIMINADO"
        db.execute("SELECT count(*) FROM computer_assignments WHERE computer_id = %s AND activo", (pc,))
        assert db.fetchone()[0] == 0, f"ronda {ronda}: eliminado con asignación activa"


# ---------- R2-H4: lista positiva y transiciones ----------
@pytest.mark.parametrize("estado", ["ACTIVO", "INACTIVO", "NUEVO", "MANTENIMIENTO"])
def test_estados_ajenos_a_computadoras_400(client, serie_unica, estado):
    crear_computadora(client, serie_unica)
    assert client.put(f"/equipos/computers/{serie_unica}/status", json={"nuevo_estado": estado}).status_code == 400


def test_transiciones_de_estado(client, db, serie_unica):
    _, pc = crear_computadora(client, serie_unica)  # nace DISPONIBLE
    url = f"/equipos/computers/{serie_unica}/status"
    assert client.put(url, json={"nuevo_estado": "DISPONIBLE"}).status_code == 400  # mismo estado
    assert client.put(url, json={"nuevo_estado": "BAJA"}).status_code == 200
    assert client.put(url, json={"nuevo_estado": "BAJA"}).status_code == 400
    assert client.put(url, json={"nuevo_estado": "DISPONIBLE"}).status_code == 200
    assert estado_computadora(db, pc) == "DISPONIBLE"


# ---------- R2-M1: limitador por IP y expulsión ----------
def test_limite_por_ip_aunque_se_cambie_de_usuario(client_anonimo, monkeypatch):
    monkeypatch.setattr(login, "MAX_FALLOS_IP", 4)
    for i in range(4):
        r = client_anonimo.post("/auth/login", json={"username": f"t-ip-{uuid.uuid4().hex[:6]}-{i}", "password": "x"})
        assert r.status_code == 401
    r = client_anonimo.post("/auth/login", json={"username": "otro-usuario-nuevo", "password": "x"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_limitador_expulsa_las_entradas_mas_antiguas(monkeypatch):
    monkeypatch.setattr(login, "_MAX_CLAVES", 3)
    for i in range(6):
        login._registrar_fallo((f"u{i}", "ip"), f"ip{i}")
    assert len(login._fallos) == 3 and len(login._fallos_ip) == 3
    assert ("u5", "ip") in login._fallos and ("u0", "ip") not in login._fallos


# ---------- R2-H2: eliminar accesorio asignado ----------
def test_eliminar_accesorio_asignado_registra_devolucion_con_autor(client, db, serie_unica, usuarios_sesion):
    pid = _persona(client, serie_unica)
    tipo = client.get("/equipos/accessory-types").json()[0]["id"]
    acc = client.post("/equipos/accessories", json={"accessory_type_id": tipo, "marca": "M", "modelo": "M1",
                                                    "numero_serie": serie_unica, "tipo_propiedad": "PROPIO"})
    acc_id = acc.json()["accessory_id"]
    assert client.post("/equipos/assign/accessory", json={"accessory_id": acc_id, "person_id": pid}).status_code == 200
    assert client.delete(f"/equipos/accessories/{acc_id}").status_code == 200
    db.execute("SELECT usuario_registro, person_id FROM accessory_history "
               "WHERE accessory_id = %s AND tipo_movimiento = 'DEVOLUCION'", (acc_id,))
    assert db.fetchall() == [(usuarios_sesion["ADMIN"][1], pid)]
    db.execute("SELECT count(*) FROM person_accessories WHERE accessory_id = %s AND activo", (acc_id,))
    assert db.fetchone()[0] == 0


def test_eliminar_accesorio_sin_asignar_no_registra_devolucion(client, db, serie_unica):
    tipo = client.get("/equipos/accessory-types").json()[0]["id"]
    acc_id = client.post("/equipos/accessories", json={"accessory_type_id": tipo, "marca": "M", "modelo": "M1",
                                                       "numero_serie": serie_unica, "tipo_propiedad": "PROPIO"}).json()["accessory_id"]
    assert client.delete(f"/equipos/accessories/{acc_id}").status_code == 200
    db.execute("SELECT count(*) FROM accessory_history WHERE accessory_id = %s AND tipo_movimiento = 'DEVOLUCION'", (acc_id,))
    assert db.fetchone()[0] == 0


# ---------- RENTADO ----------
def test_tipo_propiedad_rentado_en_crear_y_reactivar(client, db, serie_unica):
    hw = client.post("/equipos/hardware", json=_spec(serie_unica)).json()["hardware_id"]
    cuerpo = {"hardware_spec_id": hw, "numero_serie": serie_unica, "tipo_propiedad": "rentado",
              "tarifa_mensual": 10, "fecha_recepcion_proveedor": date.today().isoformat(), "anio_fabricacion": 2022}
    r = client.post("/equipos/computers", json=cuerpo)
    assert r.status_code == 200, r.text
    pc = r.json()["computer_id"]
    db.execute("SELECT tipo_propiedad FROM computers WHERE id = %s", (pc,))
    assert db.fetchone()[0] == "RENTADO"
    # Reactivar un equipo eliminado es la vía que actualiza tipo_propiedad
    assert client.delete(f"/equipos/computers/{serie_unica}").status_code == 200
    r = client.post("/equipos/computers", json={**cuerpo, "tipo_propiedad": "ARRIENDO"})
    assert r.status_code == 200 and r.json()["computer_id"] == pc
    r = client.post("/equipos/computers", json={**cuerpo, "tipo_propiedad": "REGALADO"})
    assert r.status_code == 422
