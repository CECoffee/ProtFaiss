"""User admin routes — thin wrapper over daemon IPC."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.api.ipc_client import get_client, IpcError

router = APIRouter(prefix="/admin", tags=["admin"])


class UserPatch(BaseModel):
    role: Optional[str] = None
    gpu_quota: Optional[int] = None
    is_active: Optional[bool] = None
    email: Optional[str] = None


def _ctx(admin: dict) -> dict:
    return {"source": "api", "user_id": admin["id"], "role": "admin"}


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router.get("/users")
async def list_users(limit: int = 50, offset: int = 0, admin: dict = Depends(require_admin)):
    return await _call("user.list", {"limit": limit, "offset": offset}, _ctx(admin))


@router.get("/users/{user_id}")
async def get_user(user_id: str, admin: dict = Depends(require_admin)):
    return await _call("user.get", {"user_id": user_id}, _ctx(admin))


@router.patch("/users/{user_id}")
async def update_user(user_id: str, patch: UserPatch, admin: dict = Depends(require_admin)):
    params = {"user_id": user_id, **patch.model_dump(exclude_none=True)}
    return await _call("user.update", params, _ctx(admin))


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    return await _call("user.delete", {"user_id": user_id}, _ctx(admin))


@router.get("/stats")
async def system_stats(admin: dict = Depends(require_admin)):
    return await _call("system.stats", {}, _ctx(admin))


@router.post("/reload-config")
async def reload_config(admin: dict = Depends(require_admin)):
    return await _call("config.reload", {}, _ctx(admin))
