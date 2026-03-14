import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.auth.dependencies import require_admin, get_current_user
from app.auth.db_operations import (
    blocking_list_users, blocking_get_user_by_id,
    blocking_update_user, blocking_delete_user,
)
from app.search.tasks import BLOCKING_EXECUTOR
from app.core import config_loader

router = APIRouter(prefix="/admin", tags=["admin"])


class UserPatch(BaseModel):
    role: Optional[str] = None
    gpu_quota: Optional[int] = None
    is_active: Optional[bool] = None
    email: Optional[str] = None


@router.get("/users")
async def list_users(
    limit: int = 50,
    offset: int = 0,
    admin: dict = Depends(require_admin),
):
    loop = asyncio.get_event_loop()
    users = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_list_users, limit, offset)
    return {"users": users, "limit": limit, "offset": offset}


@router.get("/users/{user_id}")
async def get_user(user_id: str, admin: dict = Depends(require_admin)):
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_user_by_id, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user


@router.patch("/users/{user_id}")
async def update_user(user_id: str, patch: UserPatch, admin: dict = Depends(require_admin)):
    # Validate gpu_quota against system limit
    if patch.gpu_quota is not None:
        total_slots = config_loader.get("scheduler", "total_gpu_slots", 4)
        if patch.gpu_quota < 0:
            raise HTTPException(400, "gpu_quota must be >= 0")
        if patch.gpu_quota > total_slots:
            raise HTTPException(
                400, f"gpu_quota cannot exceed system total_gpu_slots ({total_slots})"
            )
    if patch.role is not None and patch.role not in ("user", "admin"):
        raise HTTPException(400, "role must be 'user' or 'admin'")

    loop = asyncio.get_event_loop()
    updated = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_update_user, user_id, patch.model_dump(exclude_none=True)
    )
    if not updated:
        raise HTTPException(404, "User not found")
    return updated


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    # Prevent self-deletion
    if user_id == admin["id"]:
        raise HTTPException(400, "Cannot delete your own account")
    loop = asyncio.get_event_loop()
    deleted = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_delete_user, user_id)
    if not deleted:
        raise HTTPException(404, "User not found")
    return {"deleted": user_id}


@router.get("/stats")
async def system_stats(admin: dict = Depends(require_admin)):
    from app.core.db import get_pool
    from app.scheduler.gpu_pool import get_pool as get_gpu_pool
    loop = asyncio.get_event_loop()

    def _stats():
        pool = get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                user_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM datasets")
                dataset_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM gpu_tasks WHERE status = 'running'")
                running_tasks = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM gpu_tasks WHERE status = 'pending'")
                pending_tasks = cur.fetchone()[0]
            return {
                "user_count": user_count,
                "dataset_count": dataset_count,
                "running_gpu_tasks": running_tasks,
                "pending_gpu_tasks": pending_tasks,
                "gpu_pool": get_gpu_pool().snapshot(),
            }
        finally:
            pool.putconn(conn)

    return await loop.run_in_executor(BLOCKING_EXECUTOR, _stats)
