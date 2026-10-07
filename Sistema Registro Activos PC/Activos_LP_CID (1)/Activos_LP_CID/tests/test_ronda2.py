"""Segunda ronda de seguridad: autorización por método, revocación, autoría, concurrencia, estados,
limitador de login, docs desactivados y validación de entrada (solo contra la copia local)."""
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient

import auth
from app import app, crear_app
from conftest import _conectar
from test_api import crear_computadora, estado_computadora

RAIZ = Path(__file__).resolve().parent.parent


def _persona(client, serie):
    compania = client.get("/equipos/companies").json()[0]["id"]
    r = client.post("/equipos/people", json={"cedula": serie[-10:], "nombre": "PRUEBA R2", "company_id": compania})
    assert r.status_code == 200, r.text
    return r.json()["person_id"]


def _crear_usuario(rol, clave="Clave-de-prueba-1"):
    nombre = f"t-r2-{uuid.uuid4().hex[:10]}"
    conn = _conectar()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (username, password, role) VALUES (%s,%s,%s) RETURNING id",
                    (nombre, bcrypt.hashpw(clave.encode(), bcrypt.gensalt()).decode(), rol))
        uid = cur.fetchone()[0]
    return conn, uid, nombre


# ---------- H1: USER = solo lectura ----------
def test_usuario_puede_leer(client_usuario):
    for ruta in ("/equipos/companies", "/equipos/vista/inventario-general", "/mantenimiento"):
        assert client_usuario.get(ruta).status_code == 200


@pytest.mark.parametrize("metodo,ruta,cuerpo", [
    ("post", "/equipos/companies", {"nombre": "X"}),
    ("post", "/equipos/people", {"cedula": "1", "nombre": "X", "company_id": 1}),
    ("put", "/equipos/people/1", {"cedula": "1", "nombre": "X", "company_id": 1}),
    ("delete", "/equipos/people/1", None),
    ("post", "/equipos/assign/computer", {"computer_id": 1, "person_id": 1}),
    ("put", "/equipos/computers/X/status", {"nuevo_estado": "BAJA"}),
    ("delete", "/equipos/computers/X", None),
    ("post", "/equipos/unassign/full/1", None),
    ("post", "/mantenimiento", {"computer_id": 1, "tipo_mantenimiento": "PREVENTIVO", "descripcion": "x"}),
    ("put", "/mantenimiento/1", {"tipo_mantenimiento": "PREVENTIVO", "descripcion": "x"}),
    ("delete", "/mantenimiento/1", None),
])
def test_usuario_no_puede_escribir_403(client_usuario, metodo, ruta, cuerpo):
    r = getattr(client_usuario, metodo)(ruta, **({"json": cuerpo} if cuerpo is not None else {}))
    assert r.status_code == 403
    assert r.json()["detail"] == "Se requiere rol ADMIN"


# ---------- H1b: revocación y rol vigente ----------
def test_usuario_borrado_pierde_acceso_401(client_anonimo):
    conn, uid, nombre = _crear_usuario("ADMIN")
    h = {"Authorization": f"Bearer {auth.crear_token(uid, nombre, 'ADMIN')}"}
    assert client_anonimo.get("/equipos/companies", headers=h).status_code == 200
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (uid,))
    conn.close()
    r = client_anonimo.get("/equipos/companies", headers=h)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_rol_degradado_se_aplica_aunque_el_token_diga_admin(client_anonimo):
    conn, uid, nombre = _crear_usuario("ADMIN")
    h = {"Authorization": f"Bearer {auth.crear_token(uid, nombre, 'ADMIN')}"}
    try:
        assert client_anonimo.post("/equipos/companies", json={"nombre": f"CIA {nombre}"[:100]}, headers=h).status_code == 200
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role = 'USER' WHERE id = %s", (uid,))
        assert client_anonimo.get("/equipos/companies", headers=h).status_code == 200
        assert client_anonimo.post("/equipos/companies", json={"nombre": "OTRA"}, headers=h).status_code == 403
        assert client_anonimo.post("/auth/register", headers=h,
                                   json={"username": "x-no", "password": "Clave-larga-1", "role": "USER"}).status_code == 403
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM companies WHERE nombre = %s", (f"CIA {nombre}"[:100],))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.close()


def test_token_con_usuario_renombrado_o_ajeno_401(client_anonimo, usuarios_sesion):
    uid, _ = usuarios_sesion["ADMIN"]
    h = {"Authorization": f"Bearer {auth.crear_token(uid, 'otro-nombre', 'ADMIN')}"}
    assert client_anonimo.get("/equipos/companies", headers=h).status_code == 401


# ---------- H2: autoría ----------
def test_mantenimiento_ignora_usuario_registro_del_cuerpo(client, db, usuarios_sesion):

    db.execute("SELECT id FROM computers LIMIT 1")
    pc = db.fetchone()[0]
    r = client.post("/mantenimiento", json={"computer_id": pc, "tipo_mantenimiento": "PREVENTIVO",
                                            "descripcion": "Autoria", "usuario_registro": "suplantado"})
    assert r.status_code == 200, r.text
    mid = r.json()["maintenance_id"]
    try:
        db.execute("SELECT usuario_registro FROM computer_maintenance WHERE id = %s", (mid,))
        assert db.fetchone()[0] == usuarios_sesion["ADMIN"][1]
    finally:
        client.delete(f"/mantenimiento/{mid}")


def test_movimientos_de_activos_usan_usuario_autenticado(client, db, serie_unica, usuarios_sesion):
    admin = usuarios_sesion["ADMIN"][1]
    pid = _persona(client, serie_unica)
    _, pc = crear_computadora(client, serie_unica)
    tipo = client.get("/equipos/accessory-types").json()[0]["id"]
    acc = client.post("/equipos/accessories", json={
        "accessory_type_id": tipo, "marca": "M", "modelo": "M1", "numero_serie": serie_unica, "tipo_propiedad": "PROPIO"})
    assert acc.status_code == 200, acc.text
    acc_id = acc.json()["accessory_id"]
    assert client.post("/equipos/assign/computer", json={"computer_id": pc, "person_id": pid}).status_code == 200
    assert client.post("/equipos/assign/accessory", json={"accessory_id": acc_id, "person_id": pid}).status_code == 200
    assert client.put(f"/equipos/unassign/accessory/{acc_id}").status_code == 200
    assert client.put(f"/equipos/unassign/computer/{pc}").status_code == 200
    db.execute("SELECT DISTINCT usuario_registro FROM delivery_history WHERE computer_id = %s", (pc,))
    assert {f[0] for f in db.fetchall()} == {admin}
    db.execute("SELECT DISTINCT usuario_registro FROM accessory_history WHERE accessory_id = %s", (acc_id,))
    assert {f[0] for f in db.fetchall()} == {admin}


# ---------- H3: concurrencia ----------
def test_una_computadora_activa_por_persona_bajo_concurrencia(client, db, serie_unica):
    for ronda in range(3):
        pid = _persona(client, f"{serie_unica}{ronda}")
        pcs = [crear_computadora(client, f"{serie_unica}-{ronda}-{i}")[1] for i in range(2)]
        barrera = threading.Barrier(2)
        codigos = []

        def asignar(pc):
            c = TestClient(app)
            c.headers.update(client.headers)
            barrera.wait()
            codigos.append(c.post("/equipos/assign/computer", json={"computer_id": pc, "person_id": pid}).status_code)

        hilos = [threading.Thread(target=asignar, args=(pc,)) for pc in pcs]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        assert sorted(codigos) == [200, 400], codigos
        db.execute("SELECT count(*) FROM computer_assignments WHERE person_id = %s AND activo", (pid,))
        assert db.fetchone()[0] == 1
        client.post(f"/equipos/unassign/full/{pid}")


# ---------- H4: cambio de estado ----------
def test_estado_con_flujo_propio_se_rechaza(client, serie_unica):
    crear_computadora(client, serie_unica)
    for estado in ("ELIMINADO", "ASIGNADO"):
        r = client.put(f"/equipos/computers/{serie_unica}/status", json={"nuevo_estado": estado})
        assert r.status_code == 400, estado
    assert buscar(client, serie_unica) is not None


def buscar(client, serie):
    return next((e for e in client.get("/equipos/vista/inventario-general").json() if e["numero_serie"] == serie), None)


def test_baja_cierra_asignacion_y_acepta_minusculas(client, db, serie_unica):
    pid = _persona(client, serie_unica)
    _, pc = crear_computadora(client, serie_unica)
    client.post("/equipos/assign/computer", json={"computer_id": pc, "person_id": pid})
    r = client.put(f"/equipos/computers/{serie_unica}/status", json={"nuevo_estado": "baja"})
    assert r.status_code == 200, r.text
    assert estado_computadora(db, pc) == "BAJA"
    db.execute("SELECT count(*) FROM computer_assignments WHERE computer_id = %s AND activo", (pc,))
    assert db.fetchone()[0] == 0


def test_estado_de_equipo_inexistente_404(client):
    assert client.put("/equipos/computers/NO-EXISTE-XYZ/status", json={"nuevo_estado": "DISPONIBLE"}).status_code == 404


# ---------- M1: limitador de login ----------
def test_limitador_login_429_con_retry_after(client_anonimo):
    cuerpo = {"username": "t-rl-" + uuid.uuid4().hex[:8], "password": "mala"}
    for _ in range(5):
        assert client_anonimo.post("/auth/login", json=cuerpo).status_code == 401
    r = client_anonimo.post("/auth/login", json=cuerpo)
    assert r.status_code == 429
    assert 0 < int(r.headers["retry-after"]) <= 15 * 60
    # otro usuario desde la misma IP no está bloqueado
    assert client_anonimo.post("/auth/login", json={**cuerpo, "username": "t-rl-otro"}).status_code == 401


def test_login_correcto_reinicia_el_contador(client_anonimo):
    conn, uid, nombre = _crear_usuario("USER", clave="Clave-correcta-1")
    try:
        for _ in range(4):
            assert client_anonimo.post("/auth/login", json={"username": nombre, "password": "mala"}).status_code == 401
        assert client_anonimo.post("/auth/login", json={"username": nombre, "password": "Clave-correcta-1"}).status_code == 200
        for _ in range(4):  # si no se hubiera reiniciado, el 2.º ya daría 429
            assert client_anonimo.post("/auth/login", json={"username": nombre, "password": "mala"}).status_code == 401
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.close()


def test_login_limites_de_longitud(client_anonimo):
    assert client_anonimo.post("/auth/login", json={"username": "a" * 101, "password": "x"}).status_code == 422
    assert client_anonimo.post("/auth/login", json={"username": "a", "password": "x" * 129}).status_code == 422


# ---------- M2 / L1 / L2 ----------
def test_jwt_secret_corto_impide_arrancar():
    r = subprocess.run([sys.executable, "-c", "import auth"], cwd=RAIZ, capture_output=True, text=True,
                       env={**__import__("os").environ, "JWT_SECRET": "corto"})
    assert r.returncode != 0 and "JWT_SECRET" in r.stderr


def test_docs_desactivados_por_defecto(client_anonimo):
    for ruta in ("/docs", "/redoc", "/openapi.json"):
        assert client_anonimo.get(ruta).status_code == 404


def test_docs_se_habilitan_explicitamente():
    c = TestClient(crear_app(True))
    assert c.get("/docs").status_code == 200 and c.get("/openapi.json").status_code == 200


def test_register_rechaza_password_de_mas_de_72_bytes(client_anonimo, token_usuario):
    h = token_usuario("ADMIN")
    larga = "ñ" * 40  # 40 caracteres = 80 bytes
    r = client_anonimo.post("/auth/register", headers=h, json={"username": "t-larga", "password": larga, "role": "USER"})
    assert r.status_code == 422


# ---------- M5: validación de entrada ----------
@pytest.mark.parametrize("ruta,cuerpo", [
    ("/equipos/hardware", {"tipo_equipo": "Laptop"}),
    ("/equipos/hardware", {"tipo_equipo": "Laptop", "marca": "M", "modelo": "X", "procesador": "P", "ram_gb": "mucha",
                           "almacenamiento": "1", "sistema_operativo": "W"}),
    ("/equipos/computers", {"numero_serie": "X"}),
    ("/equipos/computers", {"hardware_spec_id": 1, "numero_serie": "X", "tipo_propiedad": "REGALADO", "anio_fabricacion": 2020}),
    ("/equipos/accessories", {"marca": "M"}),
    ("/equipos/assign/computer", {"computer_id": 1}),
    ("/equipos/assign/accessory", {"person_id": 1}),
    ("/equipos/companies", {}),
    ("/equipos/computers/X/status", {}),
])
def test_entrada_invalida_da_422_no_500(client, ruta, cuerpo):
    metodo = client.put if ruta.endswith("/status") else client.post
    assert metodo(ruta, json=cuerpo).status_code == 422


def test_asignar_persona_inexistente_400(client, serie_unica):
    _, pc = crear_computadora(client, serie_unica)
    r = client.post("/equipos/assign/computer", json={"computer_id": pc, "person_id": 99999999})
    assert r.status_code == 400
