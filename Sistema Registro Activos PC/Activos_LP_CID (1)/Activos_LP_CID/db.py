"""Pool de conexiones PostgreSQL compartido (creacion perezosa en el primer uso)."""
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from psycopg2 import pool

logger = logging.getLogger(__name__)

_pool = None
_semaforo = None
_candado = threading.Lock()


def _obtener_pool():
    global _pool, _semaforo
    if _pool is None:
        with _candado:
            if _pool is None:
                load_dotenv(Path(__file__).with_name(".env"))  # no sobreescribe variables ya definidas
                minimo = int(os.getenv("DB_POOL_MIN", "1"))
                maximo = int(os.getenv("DB_POOL_MAX", "10"))
                _pool = pool.ThreadedConnectionPool(
                    minimo,
                    maximo,
                    host=os.getenv("DB_HOST"),
                    port=os.getenv("DB_PORT"),
                    database=os.getenv("DB_NAME"),
                    user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"),
                )
                # Evita PoolError cuando hay mas hilos que conexiones: los extra esperan
                _semaforo = threading.BoundedSemaphore(maximo)
    return _pool


@contextmanager
def get_conn():
    """Entrega una conexion del pool con la misma semantica que `with psycopg2.connect()`:
    commit al salir sin error, rollback si hubo excepcion. Siempre la devuelve al pool."""
    p = _obtener_pool()
    _semaforo.acquire()
    conn = None
    try:
        conn = p.getconn()
        try:
            yield conn
            conn.commit()
        except BaseException:
            if not conn.closed:
                conn.rollback()
            raise
    finally:
        if conn is not None:
            try:
                p.putconn(conn, close=bool(conn.closed))
            except Exception:
                logger.exception("No se pudo devolver la conexion al pool")
        _semaforo.release()


def cerrar_pool():
    global _pool, _semaforo
    with _candado:
        if _pool is not None:
            _pool.closeall()
            _pool = None
            _semaforo = None
