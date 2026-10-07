import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).with_name(".env"))  # antes de importar auth (exige JWT_SECRET)

from activos_equipos import router as activos_equipos_router  # noqa: E402
from db import cerrar_pool  # noqa: E402
from login import router as login_router  # noqa: E402
from mantenimiento import router as mantenimiento_router  # noqa: E402
from printers import router as printers_router  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    cerrar_pool()


def crear_app(habilitar_docs: bool = None) -> FastAPI:
    if habilitar_docs is None:
        habilitar_docs = os.getenv("ENABLE_DOCS", "").strip().lower() == "true"

    app = FastAPI(
        title="KEYCID365 - Sistema de Activos",
        lifespan=lifespan,
        # /docs, /redoc y /openapi.json solo con ENABLE_DOCS=true
        docs_url="/docs" if habilitar_docs else None,
        redoc_url="/redoc" if habilitar_docs else None,
        openapi_url="/openapi.json" if habilitar_docs else None,
    )

    # ==========================================
    # CONFIGURACIÓN DE CORS (Permisos de acceso)
    # ==========================================
    origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]
    # Orígenes adicionales separados por coma (p. ej. el frontend desplegado)
    origins += [o.strip() for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(activos_equipos_router)
    app.include_router(login_router)
    app.include_router(mantenimiento_router)
    app.include_router(printers_router)
    return app


app = crear_app()
