from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware # <--- 1. Importar el middleware
from activos_equipos import router as activos_equipos_router
from login import router as login_router

app = FastAPI(title="Sistema de Activos")

# ==========================================
# CONFIGURACIÓN DE CORS (Permisos de acceso)
# ==========================================
origins = [
    "http://localhost:3000", # La dirección de tu proyecto React
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Permitir todos los métodos (GET, POST, PUT, DELETE)
    allow_headers=["*"], # Permitir todos los encabezados
)
# ==========================================

app.include_router(activos_equipos_router)
app.include_router(login_router)