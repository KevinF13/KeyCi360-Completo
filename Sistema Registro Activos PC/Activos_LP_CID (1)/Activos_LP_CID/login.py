import hmac
import logging
import threading
import time
from collections import deque
from typing import Literal

import bcrypt
import psycopg2.errors
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from auth import EXPIRA_MINUTOS, crear_token, solo_admin
from db import get_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# Hash de relleno para igualar el tiempo de respuesta (usuario inexistente / ruta legada)
_HASH_RELLENO = bcrypt.hashpw(b"relleno", bcrypt.gensalt())

# ---------- Limitador de intentos fallidos (en memoria, por proceso) ----------
# Dos contadores independientes sobre la misma ventana: (username, IP) con MAX_FALLOS, y solo IP con
# MAX_FALLOS_IP (evita rotar usuarios desde una misma IP). Al llenarse el almacenamiento se expulsan las
# entradas vencidas y luego las más antiguas, así la memoria siempre queda acotada.
# RIESGO ACEPTADO: el estado vive en este proceso, no se comparte entre procesos/workers. El despliegue
# actual es un único proceso uvicorn. Si se escala a varios workers, mover estos contadores a la BD o a Redis.
MAX_FALLOS = 5
MAX_FALLOS_IP = 20
VENTANA_SEGUNDOS = 15 * 60
_MAX_CLAVES = 10000
_fallos: dict = {}      # (username, ip) -> deque de marcas de tiempo
_fallos_ip: dict = {}   # ip -> deque de marcas de tiempo
_candado = threading.Lock()


def _clave(username: str, ip: str) -> tuple:
    return (username.strip().lower(), ip)


def _espera(almacen: dict, clave, maximo: int, ahora: float) -> int:
    intentos = almacen.get(clave)
    if not intentos:
        return 0
    while intentos and ahora - intentos[0] >= VENTANA_SEGUNDOS:
        intentos.popleft()
    if not intentos:
        almacen.pop(clave, None)
        return 0
    if len(intentos) >= maximo:
        return max(1, int(VENTANA_SEGUNDOS - (ahora - intentos[0])) + 1)
    return 0


def _segundos_bloqueo(clave: tuple, ip: str) -> int:
    """0 si puede intentar; si no, segundos hasta que expire el fallo más antiguo de la ventana."""
    ahora = time.monotonic()
    with _candado:
        return max(_espera(_fallos, clave, MAX_FALLOS, ahora), _espera(_fallos_ip, ip, MAX_FALLOS_IP, ahora))


def _anotar(almacen: dict, clave, ahora: float) -> None:
    if clave not in almacen and len(almacen) >= _MAX_CLAVES:
        for k in [k for k, d in almacen.items() if not d or ahora - d[-1] >= VENTANA_SEGUNDOS]:
            almacen.pop(k, None)
        while len(almacen) >= _MAX_CLAVES:  # expulsión real: las más antiguas (orden de inserción)
            almacen.pop(next(iter(almacen)))
    almacen.setdefault(clave, deque()).append(ahora)


def _registrar_fallo(clave: tuple, ip: str) -> None:
    ahora = time.monotonic()
    with _candado:
        _anotar(_fallos, clave, ahora)
        _anotar(_fallos_ip, ip, ahora)


def _reiniciar_fallos(clave: tuple) -> None:
    """Un login correcto reinicia solo el contador (username, IP); el de IP expira por ventana."""
    with _candado:
        _fallos.pop(clave, None)


def reiniciar_limitador() -> None:
    with _candado:
        _fallos.clear()
        _fallos_ip.clear()


# ---------- Modelos ----------
def _validar_72_bytes(valor: str) -> str:
    if len(valor.encode("utf-8")) > 72:
        raise ValueError("La contraseña no puede superar 72 bytes en UTF-8.")
    return valor


class Register(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8)
    role: Literal["ADMIN", "USER"]

    _password_72 = field_validator("password")(_validar_72_bytes)


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=128)


def verificar_password(ingresada: str, almacenada: str) -> bool:
    """bcrypt si el valor almacenado es un hash ($2...); si no, comparacion legada en tiempo constante."""
    entrada = ingresada.encode("utf-8")
    if almacenada.startswith("$2"):
        if len(entrada) > 72:  # register nunca guarda hashes de claves así: no puede coincidir
            return False
        try:
            return bcrypt.checkpw(entrada, almacenada.encode("utf-8"))
        except ValueError:
            return False
    bcrypt.checkpw(b"relleno", _HASH_RELLENO)  # iguala el costo de la ruta bcrypt
    return hmac.compare_digest(entrada, almacenada.encode("utf-8"))


@router.post("/register")
def register(data: Register, _admin: dict = Depends(solo_admin)):
    hashed = bcrypt.hashpw(data.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password, role) VALUES (%s,%s,%s)",
                (data.username, hashed, data.role),
            )
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    except psycopg2.Error:
        logger.exception("Error al registrar usuario")
        raise HTTPException(status_code=500, detail="Error al crear usuario.")
    return {"msg": "Usuario creado"}


@router.post("/login")
def login(data: Login, request: Request):
    ip = request.client.host if request.client else "desconocida"
    clave = _clave(data.username, ip)
    espera = _segundos_bloqueo(clave, ip)
    if espera:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos fallidos. Inténtelo de nuevo más tarde.",
            headers={"Retry-After": str(espera)},
        )

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, username, role, password FROM users WHERE username=%s", (data.username,))
            user = cur.fetchone()
    except psycopg2.Error:
        logger.exception("Error al consultar usuario en login")
        raise HTTPException(status_code=500, detail="Error al iniciar sesión.")

    if user is None:
        bcrypt.checkpw(b"relleno", _HASH_RELLENO)
        _registrar_fallo(clave, ip)
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    user_id, username, role, almacenada = user
    if not almacenada or not verificar_password(data.password, almacenada):
        _registrar_fallo(clave, ip)
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    _reiniciar_fallos(clave)
    return {
        "id": user_id,
        "username": username,
        "role": role,
        "access_token": crear_token(user_id, username, role),
        "token_type": "bearer",
        "expires_in": EXPIRA_MINUTOS * 60,
    }
