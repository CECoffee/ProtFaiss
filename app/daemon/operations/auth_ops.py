"""
Auth operations: register, login, refresh, logout, me.
Extracted from app.auth.routes.
"""
import asyncio
from datetime import datetime, timezone

from app.daemon.handler import register, HandlerError
from app.search.tasks import BLOCKING_EXECUTOR
from app.auth.password import verify_password
from app.auth.jwt import create_access_token, create_refresh_token, hash_refresh_token
from app.auth.db_operations import (
    blocking_get_user_by_username, blocking_create_user,
    blocking_store_refresh_token, blocking_get_refresh_token,
    blocking_revoke_refresh_token, blocking_get_user_by_id,
)
from app.core.db import get_pool


@register("auth.register")
async def auth_register(params: dict, context: dict) -> dict:
    username = params.get("username", "")
    password = params.get("password", "")
    email = params.get("email")

    if len(username) < 3 or len(username) > 64:
        raise HandlerError(400, "Username must be 3-64 characters")
    if len(password) < 6:
        raise HandlerError(400, "Password must be at least 6 characters")

    loop = asyncio.get_event_loop()
    existing = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_user_by_username, username)
    if existing:
        raise HandlerError(400, "Username already taken")

    user = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_create_user, username, password, email)
    return {"id": user["id"], "username": user["username"], "role": user["role"]}


@register("auth.login")
async def auth_login(params: dict, context: dict) -> dict:
    username = params.get("username", "")
    password = params.get("password", "")

    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_user_by_username, username)
    if not user or not user["is_active"]:
        raise HandlerError(401, "Invalid credentials")

    def _get_pw_hash():
        pool = get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM users WHERE id = %s", (user["id"],))
                row = cur.fetchone()
                return row[0] if row else ""
        finally:
            pool.putconn(conn)

    pw_hash = await loop.run_in_executor(BLOCKING_EXECUTOR, _get_pw_hash)
    ok = await loop.run_in_executor(BLOCKING_EXECUTOR, verify_password, password, pw_hash)
    if not ok:
        raise HandlerError(401, "Invalid credentials")

    access_token = create_access_token(user["id"], user["role"])
    raw_refresh, token_hash, expires_at = create_refresh_token()
    await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_store_refresh_token, user["id"], token_hash, expires_at
    )
    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "gpu_quota": user["gpu_quota"],
        },
    }


@register("auth.refresh")
async def auth_refresh(params: dict, context: dict) -> dict:
    raw_token = params.get("refresh_token", "")
    token_hash = hash_refresh_token(raw_token)
    loop = asyncio.get_event_loop()

    record = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_refresh_token, token_hash)
    if not record or record["revoked"]:
        raise HandlerError(401, "Invalid refresh token")

    now = datetime.now(timezone.utc)
    expires = record["expires_at"]
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        raise HandlerError(401, "Refresh token expired")

    user = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_user_by_id, record["user_id"])
    if not user or not user["is_active"]:
        raise HandlerError(401, "User not found or inactive")

    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_revoke_refresh_token, token_hash)
    access_token = create_access_token(user["id"], user["role"])
    raw_refresh, new_hash, new_expires = create_refresh_token()
    await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_store_refresh_token, user["id"], new_hash, new_expires
    )
    return {"access_token": access_token, "refresh_token": raw_refresh, "token_type": "bearer"}


@register("auth.logout")
async def auth_logout(params: dict, context: dict) -> dict:
    raw_token = params.get("refresh_token", "")
    token_hash = hash_refresh_token(raw_token)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_revoke_refresh_token, token_hash)
    return {"status": "logged out"}


@register("auth.me")
async def auth_me(params: dict, context: dict) -> dict:
    user_id = context.get("user_id")
    if not user_id:
        raise HandlerError(401, "Not authenticated")
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_user_by_id, user_id)
    if not user:
        raise HandlerError(404, "User not found")
    return user
