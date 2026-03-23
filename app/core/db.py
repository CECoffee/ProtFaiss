import os
from typing import Optional
import psycopg2
import psycopg2.pool
import threading

from . import config_loader

# module-level pool (initialized in main.startup)
DB_CONN_POOL: Optional[psycopg2.pool.ThreadedConnectionPool] = None
DB_LOCK = threading.Lock()


def get_db_config() -> dict:
    """返回已解析的 DB 连接参数（来自 config.yml + 环境变量覆盖）。
    每次调用返回新 dict，可安全修改。
    优先级：环境变量 > config.yml > _DEFAULTS。
    """
    cfg = config_loader.get_config().get("database", {})
    params = {
        "host":   os.environ.get("DB_HOST",   cfg.get("host",     "localhost")),
        "port":   int(os.environ.get("DB_PORT",   str(cfg.get("port", 5432)))),
        "dbname": os.environ.get("DB_NAME",   cfg.get("dbname",   "protein_db")),
        "user":   os.environ.get("DB_USER",   cfg.get("user",     "postgres")),
        "password": os.environ.get("DB_PASSWORD", cfg.get("password", "")),
    }
    return params


def _max_connections() -> int:
    cfg = config_loader.get_config().get("database", {})
    return int(cfg.get("max_connections", 20))


def init_db_pool():
    global DB_CONN_POOL
    if DB_CONN_POOL is None:
        db_params = get_db_config()
        max_conns = _max_connections()
        DB_CONN_POOL = psycopg2.pool.ThreadedConnectionPool(1, max_conns, **db_params)
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
