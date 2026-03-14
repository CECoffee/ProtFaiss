import asyncio
from datetime import timezone

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional

from .password import verify_password
from .jwt import create_access_token, create_refresh_token, hash_refresh_token
from .db_operations import (
    blocking_get_user_by_username, blocking_create_user,
    blocking_store_refresh_token, blocking_get_refresh_token,
    blocking_revoke_refresh_token, blocking_get_user_by_id,
)
from .dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

_EXECUTOR = None


def _get_executor():
    from app.search.tasks import BLOCKING_EXECUTOR
    return BLOCKING_EXECUTOR


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    if len(req.username) < 3 or len(req.username) > 64:
        raise HTTPException(400, "Username must be 3-64 characters")
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    loop = asyncio.get_event_loop()
    existing = await loop.run_in_executor(_get_executor(), blocking_get_user_by_username, req.username)
    if existing:
        raise HTTPException(400, "Username already taken")

    user = await loop.run_in_executor(
        _get_executor(), blocking_create_user, req.username, req.password, req.email
    )
    return {"id": user["id"], "username": user["username"], "role": user["role"]}


@router.post("/login")
async def login(req: LoginRequest):
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(_get_executor(), blocking_get_user_by_username, req.username)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Verify password in executor (bcrypt is CPU-bound)
    from .db_operations import blocking_get_user_by_username as _get
    from app.core.db import get_pool
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s", (user["id"],))
            row = cur.fetchone()
            pw_hash = row[0] if row else ""
    finally:
        pool.putconn(conn)

    ok = await loop.run_in_executor(_get_executor(), verify_password, req.password, pw_hash)
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(user["id"], user["role"])
    raw_refresh, token_hash, expires_at = create_refresh_token()
    await loop.run_in_executor(
        _get_executor(), blocking_store_refresh_token, user["id"], token_hash, expires_at
    )

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "user": {"id": user["id"], "username": user["username"], "role": user["role"], "gpu_quota": user["gpu_quota"]},
    }


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    from datetime import datetime
    token_hash = hash_refresh_token(req.refresh_token)
    loop = asyncio.get_event_loop()
    record = await loop.run_in_executor(_get_executor(), blocking_get_refresh_token, token_hash)
    if not record or record["revoked"]:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    now = datetime.now(timezone.utc)
    expires = record["expires_at"]
    if expires.tzinfo is None:
        from datetime import timezone as tz
        expires = expires.replace(tzinfo=tz.utc)
    if now > expires:
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = await loop.run_in_executor(_get_executor(), blocking_get_user_by_id, record["user_id"])
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Rotate: revoke old, issue new
    await loop.run_in_executor(_get_executor(), blocking_revoke_refresh_token, token_hash)
    access_token = create_access_token(user["id"], user["role"])
    raw_refresh, new_hash, new_expires = create_refresh_token()
    await loop.run_in_executor(
        _get_executor(), blocking_store_refresh_token, user["id"], new_hash, new_expires
    )

    return {"access_token": access_token, "refresh_token": raw_refresh, "token_type": "bearer"}


@router.post("/logout")
async def logout(req: RefreshRequest):
    token_hash = hash_refresh_token(req.refresh_token)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_get_executor(), blocking_revoke_refresh_token, token_hash)
    return {"status": "logged out"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user
