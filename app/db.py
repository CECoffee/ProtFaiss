from typing import List, Tuple, Optional
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

def close_db_pool():
    global DB_CONN_POOL
    if DB_CONN_POOL:
        try:
            DB_CONN_POOL.closeall()
        finally:
            DB_CONN_POOL = None

def blocking_db_get_rows(ids: List[int]) -> List[Tuple]:
    """阻塞式 DB 查询，返回 rows"""
    if not ids:
        return []
    conn = None
    try:
        conn = DB_CONN_POOL.getconn()
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(ids))
        cur.execute(f"""
            SELECT id, original_header, sequence, ph_processed, ko_number, ec_number
            FROM "proteins_mock_1M"
            WHERE id IN ({placeholders})
        """, tuple(ids))
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        if conn:
            DB_CONN_POOL.putconn(conn)
