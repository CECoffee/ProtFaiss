from typing import List, Tuple

from app.core.db import get_pool


def blocking_db_get_rows_from_table(table_name: str, ids: List[int]) -> List[Tuple]:
    """Query rows from a specific table by IDs."""
    if not ids:
        return []
    if not table_name:
        raise ValueError("table_name must not be empty")
    conn = None
    pool = get_pool()
    try:
        conn = pool.getconn()
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(ids))
        cur.execute(f"""
            SELECT id, original_header, sequence, ph_processed, ko_number, ec_number
            FROM "{table_name}"
            WHERE id IN ({placeholders})
        """, tuple(ids))
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        if conn:
            pool.putconn(conn)
