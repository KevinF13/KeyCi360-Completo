"""
Pruebas de la API contra una COPIA local de la base de datos.

Nunca se ejecutan contra la base real: la conexión se toma de las variables
TEST_DB_* y se aborta si el host no es local.

    set TEST_DB_HOST=localhost
    set TEST_DB_PORT=5433
    set TEST_DB_NAME=keycid365_test
    set TEST_DB_USER=postgres
    set TEST_DB_PASSWORD=
    python -m pytest tests -v
"""
import os
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest

HOSTS_PERMITIDOS = {"localhost", "127.0.0.1", "::1"}

_host = os.environ.get("TEST_DB_HOST", "")
if _host not in HOSTS_PERMITIDOS:
    pytest.exit(
        f"TEST_DB_HOST='{_host}' no es local. Las pruebas solo corren contra una copia local de la BD.",
        returncode=2,
    )

# Se fijan ANTES de importar la app; load_dotenv() no sobreescribe variables existentes,
# así que el .env de producción queda ignorado.
for clave in ("HOST", "PORT", "NAME", "USER", "PASSWORD"):
    os.environ[f"DB_{clave}"] = os.environ.get(f"TEST_DB_{clave}", "")

# Secreto JWT solo para pruebas (la app no arranca sin JWT_SECRET)
os.environ["JWT_SECRET"] = "secreto-solo-para-pruebas-" + "x" * 32
os.environ["ENABLE_DOCS"] = "false"  # las pruebas verifican que /docs queda desactivado por defecto

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
from auth import crear_token  # noqa: E402

# Usuario de pruebas indicado: FAJARDO RODRIGUEZ KEVIN GUSTAVO
KEVIN_ID = 72
KEVIN_CEDULA = "1726375890"


def _conectar():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


@pytest.fixture(scope="session", autouse=True)
def verificar_bd_local():
    with _conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database(), inet_server_addr()")
        nombre, addr = cur.fetchone()
    assert nombre.endswith("_test"), f"La BD '{nombre}' no parece de pruebas"
    assert addr is None or str(addr) in {"127.0.0.1", "::1"}, f"Servidor no local: {addr}"


@pytest.fixture(scope="session")
def usuarios_sesion(verificar_bd_local):
    """Un ADMIN y un USER reales en la copia local (usuario_actual comprueba la BD); se borran al final."""
    sufijo = uuid.uuid4().hex[:8]
    conn = _conectar()
    conn.autocommit = True
    ids = {}
    with conn.cursor() as cur:
        for rol in ("ADMIN", "USER"):
            nombre = f"t-sesion-{rol.lower()}-{sufijo}"
            cur.execute("INSERT INTO users (username, password, role) VALUES (%s,%s,%s) RETURNING id",
                        (nombre, "no-se-usa-" + sufijo, rol))
            ids[rol] = (cur.fetchone()[0], nombre)
    yield ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username LIKE %s", (f"t-sesion-%-{sufijo}",))
    conn.close()


def _cabecera(uid, nombre, rol):
    return {"Authorization": f"Bearer {crear_token(uid, nombre, rol)}"}


@pytest.fixture(scope="session")
def client(usuarios_sesion):
    """Cliente autenticado como ADMIN."""
    c = TestClient(app)
    uid, nombre = usuarios_sesion["ADMIN"]
    c.headers.update(_cabecera(uid, nombre, "ADMIN"))
    return c


@pytest.fixture(scope="session")
def client_usuario(usuarios_sesion):
    """Cliente autenticado como USER (solo lectura)."""
    c = TestClient(app)
    uid, nombre = usuarios_sesion["USER"]
    c.headers.update(_cabecera(uid, nombre, "USER"))
    return c


@pytest.fixture(scope="session")
def client_anonimo():
    """Cliente sin credenciales."""
    return TestClient(app)


@pytest.fixture()
def token_usuario(usuarios_sesion):
    """Devuelve una funcion que genera cabeceras Authorization de los usuarios reales de prueba."""
    def _hacer(role="USER"):
        uid, nombre = usuarios_sesion[role]
        return _cabecera(uid, nombre, role)
    return _hacer


@pytest.fixture(autouse=True)
def _limpiar_limitador():
    from login import reiniciar_limitador
    reiniciar_limitador()
    yield
    reiniciar_limitador()


@pytest.fixture()
def db():
    conn = _conectar()
    conn.autocommit = True
    with conn.cursor() as cur:
        yield cur
    conn.close()


@pytest.fixture()
def serie_unica():
    return f"TEST-{uuid.uuid4().hex[:12]}".upper()
