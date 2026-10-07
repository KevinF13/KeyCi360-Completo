"""Autenticacion JWT (HS256): emision y verificacion de tokens, dependencias de FastAPI."""
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import psycopg2
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db import get_conn

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).with_name(".env"))

ALGORITMO = "HS256"
EXPIRA_MINUTOS = 30

MIN_LONGITUD_SECRETO = 32
METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}

JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
if len(JWT_SECRET) < MIN_LONGITUD_SECRETO:
    raise RuntimeError(
        f"JWT_SECRET falta o tiene menos de {MIN_LONGITUD_SECRETO} caracteres. Defínalo en el .env "
        "(p. ej. python -c \"import secrets; print(secrets.token_urlsafe(48))\")."
    )

_bearer = HTTPBearer(auto_error=False)


def _no_autenticado() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )


def crear_token(user_id: int, username: str, role: str) -> str:
    ahora = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": username,
            "uid": user_id,
            "role": role,
            "iat": ahora,
            "exp": ahora + timedelta(minutes=EXPIRA_MINUTOS),
        },
        JWT_SECRET,
        algorithm=ALGORITMO,
    )


def usuario_actual(credenciales: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """Valida el JWT y confirma en BD que el usuario sigue existiendo; el rol vigente es el de la BD."""
    if credenciales is None or credenciales.scheme.lower() != "bearer":
        raise _no_autenticado()
    try:
        claims = jwt.decode(
            credenciales.credentials,
            JWT_SECRET,
            algorithms=[ALGORITMO],
            options={"require": ["exp", "sub", "uid", "role"]},
        )
        uid = int(claims["uid"])
    except (jwt.PyJWTError, TypeError, ValueError):
        raise _no_autenticado()

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT username, role FROM users WHERE id = %s", (uid,))
            fila = cur.fetchone()
    except psycopg2.Error:
        logger.exception("No se pudo verificar al usuario del token")
        raise HTTPException(status_code=503, detail="Servicio no disponible, inténtelo de nuevo.")

    if fila is None or fila[0] != claims["sub"]:
        raise _no_autenticado()
    return {"id": uid, "username": fila[0], "role": fila[1]}


def solo_admin(usuario: dict = Depends(usuario_actual)) -> dict:
    """El rol sale de la BD (no del token ni del cliente)."""
    if usuario["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="Se requiere rol ADMIN")
    return usuario


def lectura_usuario_escritura_admin(request: Request, usuario: dict = Depends(usuario_actual)) -> dict:
    """Dependencia de router: cualquier usuario autenticado puede leer (GET);
    POST/PUT/PATCH/DELETE exigen ADMIN."""
    if request.method not in METODOS_LECTURA and usuario["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="Se requiere rol ADMIN")
    return usuario
