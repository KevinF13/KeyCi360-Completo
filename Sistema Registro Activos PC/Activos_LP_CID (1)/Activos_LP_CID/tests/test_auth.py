"""Pruebas de autenticacion, autorizacion y manejo de errores (solo contra la copia local)."""
import time
import uuid
from contextlib import contextmanager

import bcrypt
import jwt
import pytest

import activos_equipos
import auth
from conftest import _conectar


@pytest.fixture()
def usuarios_prueba():
    """Crea un usuario bcrypt y uno legado (texto plano); los borra al terminar."""
    sufijo = uuid.uuid4().hex[:8]
    datos = {
        "bcrypt": (f"t-bcrypt-{sufijo}", "ClaveSegura#1"),
        "legado": (f"t-legado-{sufijo}", "ClaveLegada#2"),
    }
    conn = _conectar()
    conn.autocommit = True
    with conn.cursor() as cur:
        u, p = datos["bcrypt"]
        cur.execute("INSERT INTO users (username, password, role) VALUES (%s,%s,'USER')",
                    (u, bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()))
        u, p = datos["legado"]
        cur.execute("INSERT INTO users (username, password, role) VALUES (%s,%s,'USER')", (u, p))
    yield datos
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username LIKE %s", (f"t-%-{sufijo}",))
    conn.close()


# ---------- rutas protegidas ----------
@pytest.mark.parametrize("ruta", ["/equipos/companies", "/equipos/vista/inventario-general", "/mantenimiento"])
def test_ruta_protegida_sin_token_401(client_anonimo, ruta):
    r = client_anonimo.get(ruta)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_post_protegido_sin_token_401(client_anonimo):
    assert client_anonimo.post("/equipos/companies", json={"nombre": "X"}).status_code == 401


def test_token_invalido_401(client_anonimo):
    r = client_anonimo.get("/equipos/companies", headers={"Authorization": "Bearer no.es.un.jwt"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_token_firmado_con_otro_secreto_401(client_anonimo):
    falso = jwt.encode({"sub": "x", "uid": 1, "role": "ADMIN", "exp": int(time.time()) + 600},
                       "otro-secreto-de-al-menos-32-bytes-xxxx", algorithm="HS256")
    assert client_anonimo.get("/equipos/companies", headers={"Authorization": f"Bearer {falso}"}).status_code == 401


def test_token_expirado_401(client_anonimo):
    viejo = jwt.encode({"sub": "x", "uid": 1, "role": "ADMIN", "exp": int(time.time()) - 10},
                       auth.JWT_SECRET, algorithm="HS256")
    assert client_anonimo.get("/equipos/companies", headers={"Authorization": f"Bearer {viejo}"}).status_code == 401


def test_preflight_cors_sin_token(client_anonimo):
    r = client_anonimo.options("/equipos/companies", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200


# ---------- login ----------
def test_login_bcrypt_devuelve_token(client_anonimo, usuarios_prueba):
    u, p = usuarios_prueba["bcrypt"]
    r = client_anonimo.post("/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"id", "username", "role", "access_token", "token_type", "expires_in"}
    assert cuerpo["token_type"] == "bearer" and cuerpo["expires_in"] == 1800
    claims = jwt.decode(cuerpo["access_token"], auth.JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == u and claims["uid"] == cuerpo["id"] and claims["role"] == "USER"
    ok = client_anonimo.get("/equipos/companies", headers={"Authorization": f"Bearer {cuerpo['access_token']}"})
    assert ok.status_code == 200


def test_login_legado_texto_plano_funciona(client_anonimo, usuarios_prueba):
    u, p = usuarios_prueba["legado"]
    r = client_anonimo.post("/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200 and "access_token" in r.json()


def test_login_no_reescribe_password_legado(client_anonimo, usuarios_prueba, db):
    u, p = usuarios_prueba["legado"]
    client_anonimo.post("/auth/login", json={"username": u, "password": p})
    db.execute("SELECT password FROM users WHERE username = %s", (u,))
    assert db.fetchone()[0] == p


@pytest.mark.parametrize("quien", ["bcrypt", "legado"])
def test_login_clave_incorrecta_401(client_anonimo, usuarios_prueba, quien):
    u, _ = usuarios_prueba[quien]
    r = client_anonimo.post("/auth/login", json={"username": u, "password": "mala"})
    assert r.status_code == 401 and r.json() == {"detail": "Credenciales incorrectas"}


def test_login_usuario_inexistente_401(client_anonimo):
    r = client_anonimo.post("/auth/login", json={"username": "no-existe-" + uuid.uuid4().hex, "password": "x"})
    assert r.status_code == 401 and r.json() == {"detail": "Credenciales incorrectas"}


# ---------- register ----------
BODY = {"username": "t-reg-nuevo", "password": "OtraClave#123", "role": "USER"}


def test_register_sin_token_401(client_anonimo):
    assert client_anonimo.post("/auth/register", json=BODY).status_code == 401


def test_register_con_rol_user_403(client_anonimo, token_usuario):
    r = client_anonimo.post("/auth/register", json=BODY, headers=token_usuario("USER"))
    assert r.status_code == 403


def test_register_admin_crea_usuario_con_bcrypt(client_anonimo, token_usuario, db):
    nombre = f"t-reg-{uuid.uuid4().hex[:8]}"
    h = token_usuario("ADMIN")
    try:
        r = client_anonimo.post("/auth/register", json={**BODY, "username": nombre}, headers=h)
        assert r.status_code == 200, r.text
        db.execute("SELECT password FROM users WHERE username = %s", (nombre,))
        almacenada = db.fetchone()[0]
        assert almacenada.startswith("$2") and almacenada != BODY["password"]
        dup = client_anonimo.post("/auth/register", json={**BODY, "username": nombre}, headers=h)
        assert dup.status_code == 400 and dup.json()["detail"] == "Usuario ya existe"
        login = client_anonimo.post("/auth/login", json={"username": nombre, "password": BODY["password"]})
        assert login.status_code == 200
    finally:
        db.execute("DELETE FROM users WHERE username = %s", (nombre,))


def test_register_rol_invalido_422(client_anonimo, token_usuario):
    r = client_anonimo.post("/auth/register", json={**BODY, "role": "SUPERADMIN"}, headers=token_usuario("ADMIN"))
    assert r.status_code == 422


# ---------- errores 500 ----------
class _CursorQueFalla:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        raise RuntimeError("SECRETO-INTERNO tabla_x columna_y")


class _ConexionFalsa:
    def cursor(self, *a, **k):
        return _CursorQueFalla()

    def rollback(self):
        pass

    def commit(self):
        pass


def test_error_500_no_filtra_mensaje_interno(client, monkeypatch, caplog):
    @contextmanager
    def falsa():
        yield _ConexionFalsa()

    monkeypatch.setattr(activos_equipos, "get_conn", falsa)
    with caplog.at_level("ERROR"):
        r = client.get("/equipos/companies")
    assert r.status_code == 500
    assert "SECRETO-INTERNO" not in r.text and "tabla_x" not in r.text
    assert "SECRETO-INTERNO" in caplog.text  # pero si queda registrado en el log
