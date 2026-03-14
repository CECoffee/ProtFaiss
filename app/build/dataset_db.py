"""
PostgreSQL-backed dataset CRUD — replaces dataset_registry.py / registry_sync.py.

All functions are synchronous (blocking) and safe to call from both the main
FastAPI process (via run_in_executor) and the build worker subprocess.
"""
import time
from typing import Optional, List, Dict

from app.core.db import get_pool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_entry(row) -> Dict:
    return {
        "id": str(row[0]),
        "owner_id": str(row[1]),
        "name": row[2],
        "algorithm": row[3],
        "status": row[4],
        "visibility": row[5],
        "error_msg": row[6],
        "fasta_path": row[7],
        "index_dir": row[8],
        "db_table": row[9],
        "num_sequences": row[10],
        "num_indexed": row[11],
        "progress_step": row[12],
        "progress_pct": row[13],
        "progress_detail": row[14],
        "created_at": row[15].isoformat() if row[15] else None,
        "updated_at": row[16].isoformat() if row[16] else None,
    }


_SELECT = (
    "SELECT id, owner_id, name, algorithm, status, visibility, error_msg, "
    "fasta_path, index_dir, db_table, num_sequences, num_indexed, "
    "progress_step, progress_pct, progress_detail, created_at, updated_at "
    "FROM datasets"
)


# ---------------------------------------------------------------------------
# Dataset CRUD
# ---------------------------------------------------------------------------

def blocking_create_dataset(entry: Dict) -> Dict:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO datasets "
                "(id, owner_id, name, algorithm, status, visibility, fasta_path, index_dir, db_table) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id, owner_id, name, algorithm, status, visibility, error_msg, "
                "fasta_path, index_dir, db_table, num_sequences, num_indexed, "
                "progress_step, progress_pct, progress_detail, created_at, updated_at",
                (
                    entry["id"], entry["owner_id"], entry["name"], entry["algorithm"],
                    entry.get("status", "building"), entry.get("visibility", "private"),
                    entry.get("fasta_path"), entry.get("index_dir"), entry.get("db_table"),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_entry(row)
    finally:
        pool.putconn(conn)


def blocking_get_dataset(dataset_id: str) -> Optional[Dict]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"{_SELECT} WHERE id = %s", (dataset_id,))
            row = cur.fetchone()
            return _row_to_entry(row) if row else None
    finally:
        pool.putconn(conn)


def blocking_update_dataset(dataset_id: str, patch: Dict) -> Optional[Dict]:
    allowed = {
        "status", "error_msg", "num_sequences", "num_indexed",
        "progress_step", "progress_pct", "progress_detail",
        "visibility", "name",
    }
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return blocking_get_dataset(dataset_id)

    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            set_clause = ", ".join(f"{k} = %s" for k in fields)
            values = list(fields.values()) + [dataset_id]
            cur.execute(
                f"UPDATE datasets SET {set_clause}, updated_at = now() WHERE id = %s "
                "RETURNING id, owner_id, name, algorithm, status, visibility, error_msg, "
                "fasta_path, index_dir, db_table, num_sequences, num_indexed, "
                "progress_step, progress_pct, progress_detail, created_at, updated_at",
                values,
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_entry(row) if row else None
    finally:
        pool.putconn(conn)


def blocking_delete_dataset(dataset_id: str) -> bool:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM datasets WHERE id = %s", (dataset_id,))
            conn.commit()
            return cur.rowcount > 0
    finally:
        pool.putconn(conn)


def blocking_list_datasets_for_user(user_id: str) -> List[Dict]:
    """Return datasets owned by user + all public datasets."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"{_SELECT} WHERE owner_id = %s OR visibility = 'public' "
                "ORDER BY created_at DESC",
                (user_id,),
            )
            return [_row_to_entry(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


def blocking_list_all_datasets() -> List[Dict]:
    """Admin: return all datasets."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"{_SELECT} ORDER BY created_at DESC")
            return [_row_to_entry(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


# ---------------------------------------------------------------------------
# Active dataset per user
# ---------------------------------------------------------------------------

def blocking_get_user_active_dataset(user_id: str) -> Optional[Dict]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT d.id, d.owner_id, d.name, d.algorithm, d.status, d.visibility, "
                "d.error_msg, d.fasta_path, d.index_dir, d.db_table, d.num_sequences, "
                "d.num_indexed, d.progress_step, d.progress_pct, d.progress_detail, "
                "d.created_at, d.updated_at "
                "FROM user_active_datasets uad "
                "JOIN datasets d ON d.id = uad.dataset_id "
                "WHERE uad.user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return _row_to_entry(row) if row else None
    finally:
        pool.putconn(conn)


def blocking_get_user_active_id(user_id: str) -> Optional[str]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT dataset_id FROM user_active_datasets WHERE user_id = %s", (user_id,)
            )
            row = cur.fetchone()
            return str(row[0]) if row else None
    finally:
        pool.putconn(conn)


def blocking_set_user_active_dataset(user_id: str, dataset_id: str) -> None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_active_datasets (user_id, dataset_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET dataset_id = EXCLUDED.dataset_id",
                (user_id, dataset_id),
            )
            conn.commit()
    finally:
        pool.putconn(conn)


def blocking_clear_user_active_dataset(user_id: str) -> None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_active_datasets WHERE user_id = %s", (user_id,))
            conn.commit()
    finally:
        pool.putconn(conn)
