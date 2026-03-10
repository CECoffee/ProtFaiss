from typing import Optional
import psycopg2
import psycopg2.pool
import threading

from .config import DB_CONFIG, MAX_DB_CONNS

# module-level pool (initialized in main.startup)
DB_CONN_POOL: Optional[psycopg2.pool.ThreadedConnectionPool] = None
DB_LOCK = threading.Lock()


def init_db_pool():
    global DB_CONN_POOL
    if DB_CONN_POOL is None:
        DB_CONN_POOL = psycopg2.pool.ThreadedConnectionPool(1, MAX_DB_CONNS, **DB_CONFIG)
    return DB_CONN_POOL


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    if DB_CONN_POOL is None:
        raise RuntimeError("DB connection pool is not initialized")
    return DB_CONN_POOL


def close_db_pool():
    global DB_CONN_POOL
    if DB_CONN_POOL:
        try:
            DB_CONN_POOL.closeall()
        finally:
            DB_CONN_POOL = None
