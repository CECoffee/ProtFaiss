from typing import Optional
from datetime import datetime, timezone

from app.core.db import get_pool
from .password import hash_password


def blocking_get_user_by_username(username: str) -> Optional[dict]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, password_hash, role, gpu_quota, is_active "
                "FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_user(row)
    finally:
        pool.putconn(conn)


def blocking_get_user_by_id(user_id: str) -> Optional[dict]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, password_hash, role, gpu_quota, is_active "
                "FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_user(row)
    finally:
        pool.putconn(conn)


def blocking_create_user(username: str, password: str, email: Optional[str] = None, role: str = "user") -> dict:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, email, password_hash, role) "
                "VALUES (%s, %s, %s, %s) RETURNING id, username, email, password_hash, role, gpu_quota, is_active",
                (username, email, hash_password(password), role),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row)
    finally:
        pool.putconn(conn)


def blocking_count_users() -> int:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            return cur.fetchone()[0]
    finally:
        pool.putconn(conn)


def blocking_store_refresh_token(user_id: str, token_hash: str, expires_at: datetime) -> None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (user_id, token_hash, expires_at),
            )
            conn.commit()
    finally:
        pool.putconn(conn)


def blocking_get_refresh_token(token_hash: str) -> Optional[dict]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, expires_at, revoked FROM refresh_tokens WHERE token_hash = %s",
                (token_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {"id": str(row[0]), "user_id": str(row[1]), "expires_at": row[2], "revoked": row[3]}
    finally:
        pool.putconn(conn)


def blocking_revoke_refresh_token(token_hash: str) -> None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE refresh_tokens SET revoked = TRUE WHERE token_hash = %s", (token_hash,))
            conn.commit()
    finally:
        pool.putconn(conn)


def blocking_list_users(limit: int = 100, offset: int = 0) -> list:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, password_hash, role, gpu_quota, is_active "
                "FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            return [_row_to_user(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


def blocking_update_user(user_id: str, patch: dict) -> Optional[dict]:
    allowed = {"role", "gpu_quota", "is_active", "email"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return blocking_get_user_by_id(user_id)
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            set_clause = ", ".join(f"{k} = %s" for k in fields)
            values = list(fields.values()) + [user_id]
            cur.execute(
                f"UPDATE users SET {set_clause}, updated_at = now() WHERE id = %s "
                "RETURNING id, username, email, password_hash, role, gpu_quota, is_active",
                values,
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
    finally:
        pool.putconn(conn)


def blocking_delete_user(user_id: str) -> bool:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
            return cur.rowcount > 0
    finally:
        pool.putconn(conn)


def _row_to_user(row) -> dict:
    return {
        "id": str(row[0]),
        "username": row[1],
        "email": row[2],
        "role": row[4],
        "gpu_quota": row[5],
        "is_active": row[6],
    }
