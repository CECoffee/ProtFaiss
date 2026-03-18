"""Auth routes — thin wrapper over daemon IPC."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.api.ipc_client import get_client, IpcError
from fastapi import HTTPException

router = APIRouter(prefix="/auth", tags=["auth"])


def _ctx(user: dict) -> dict:
    return {"source": "api", "user_id": user["id"], "role": user["role"]}


def _anon_ctx() -> dict:
    return {"source": "api", "role": "anonymous"}


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    return await _call("auth.register", req.model_dump(exclude_none=True), _anon_ctx())


@router.post("/login")
async def login(req: LoginRequest):
    return await _call("auth.login", req.model_dump(), _anon_ctx())


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    return await _call("auth.refresh", req.model_dump(), _anon_ctx())


@router.post("/logout")
async def logout(req: RefreshRequest):
    return await _call("auth.logout", req.model_dump(), _anon_ctx())


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return await _call("auth.me", {}, _ctx(user))
