import os
import psycopg2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/auth", tags=["Auth"])

def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

class Register(BaseModel):
    username: str
    password: str
    role: str  # ADMIN | USER

class Login(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(data: Register):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password, role) VALUES (%s,%s,%s)",
            (data.username, data.password, data.role)
        )
        conn.commit()
        return {"msg": "Usuario creado"}
    except:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    finally:
        cur.close()
        conn.close()


@router.post("/login")
def login(data: Login):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, role FROM users WHERE username=%s AND password=%s",
        (data.username, data.password)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    return {"id": user[0], "username": user[1], "role": user[2]}
