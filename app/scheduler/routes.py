from fastapi import APIRouter, Depends
from app.auth.dependencies import get_current_user, require_admin
from .scheduler import (
    blocking_get_queue_for_user, blocking_get_full_queue,
    blocking_cancel_task, get_scheduler,
)
from .gpu_pool import get_pool as get_gpu_pool
import asyncio
from app.search.tasks import BLOCKING_EXECUTOR

router = APIRouter(tags=["gpu"])


@router.get("/gpu/queue")
async def gpu_queue(current_user: dict = Depends(get_current_user)):
    """Current user's GPU task queue."""
    loop = asyncio.get_event_loop()
    tasks = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_get_queue_for_user, current_user["id"]
    )
    pool_snapshot = get_gpu_pool().snapshot()
    return {"tasks": tasks, "pool": pool_snapshot}


@router.get("/admin/gpu/queue")
async def admin_gpu_queue(admin: dict = Depends(require_admin)):
    """Full GPU task queue (admin only)."""
    loop = asyncio.get_event_loop()
    tasks = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_full_queue)
    pool_snapshot = get_gpu_pool().snapshot()
    return {"tasks": tasks, "pool": pool_snapshot}


@router.post("/admin/gpu/tasks/{task_id}/cancel")
async def admin_cancel_task(task_id: str, admin: dict = Depends(require_admin)):
    loop = asyncio.get_event_loop()
    cancelled = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_cancel_task, task_id)
    if not cancelled:
        from fastapi import HTTPException
        raise HTTPException(404, "Task not found or not cancellable")
    return {"cancelled": task_id}
