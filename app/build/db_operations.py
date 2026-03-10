from typing import List, Tuple

from app.core.db import get_pool
from psycopg2.extras import execute_values


def blocking_create_protein_table(table_name: str) -> None:
    """Create a new protein table with the standard schema."""
    conn = None
    pool = get_pool()
    try:
        conn = pool.getconn()
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                id INTEGER PRIMARY KEY,
                original_header TEXT,
                accession TEXT,
                ko_number TEXT,
                ec_number TEXT,
                sequence TEXT,
                sequence_length INTEGER,
                ph_processed DOUBLE PRECISION
            )
        """)
        conn.commit()
        cur.close()
    finally:
        if conn:
            pool.putconn(conn)


def blocking_insert_protein_batch(table_name: str, rows: list, start_id: int) -> int:
    """
    Bulk-insert protein rows into table_name.
    rows: list of (original_header, accession, ko, ec, sequence, seq_len, ph_val)
    start_id: ID to assign to the first row
    Returns: count of inserted rows
    """
    if not rows:
        return 0
    insert_query = f"""
        INSERT INTO "{table_name}" (
            id, original_header, accession, ko_number, ec_number,
            sequence, sequence_length, ph_processed
        ) VALUES %s
        ON CONFLICT (id) DO NOTHING
    """
    records = []
    for i, (original_header, accession, ko, ec, sequence, seq_len, ph_val) in enumerate(rows):
        records.append((start_id + i, original_header, accession, ko, ec, sequence, seq_len, ph_val))

    conn = None
    pool = get_pool()
    try:
        conn = pool.getconn()
        cur = conn.cursor()
        execute_values(cur, insert_query, records)
        conn.commit()
        cur.close()
        return len(records)
    finally:
        if conn:
            pool.putconn(conn)


def blocking_drop_table(table_name: str) -> None:
    """Drop a protein table by name."""
    conn = None
    pool = get_pool()
    try:
        conn = pool.getconn()
        cur = conn.cursor()
        cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        conn.commit()
        cur.close()
    finally:
        if conn:
            pool.putconn(conn)
