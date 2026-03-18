"""
User management operations (admin only).
Extracted from app.users.routes.
"""
import asyncio

from app.daemon.handler import register, HandlerError
from app.search.tasks import BLOCKING_EXECUTOR
from app.auth.db_operations import (
    blocking_list_users, blocking_get_user_by_id,
    blocking_update_user, blocking_delete_user,
)
from app.core import config_loader


@register("user.list")
async def user_list(params: dict, context: dict) -> dict:
    limit = params.get("limit", 50)
    offset = params.get("offset", 0)
    loop = asyncio.get_event_loop()
    users = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_list_users, limit, offset)
    return {"users": users, "limit": limit, "offset": offset}


@register("user.get")
async def user_get(params: dict, context: dict) -> dict:
    user_id = params.get("user_id")
    if not user_id:
        raise HandlerError(400, "user_id required")
    loop = asyncio.get_event_loop()
    user = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_user_by_id, user_id)
    if not user:
        raise HandlerError(404, "User not found")
    return user


@register("user.update")
async def user_update(params: dict, context: dict) -> dict:
    user_id = params.get("user_id")
    if not user_id:
        raise HandlerError(400, "user_id required")

    patch = {k: v for k, v in params.items() if k != "user_id" and v is not None}

    if "gpu_quota" in patch:
        total_slots = config_loader.get("scheduler", "total_gpu_slots", 4)
        if patch["gpu_quota"] < 0:
            raise HandlerError(400, "gpu_quota must be >= 0")
        if patch["gpu_quota"] > total_slots:
            raise HandlerError(400, f"gpu_quota cannot exceed system total_gpu_slots ({total_slots})")

    if "role" in patch and patch["role"] not in ("user", "admin"):
        raise HandlerError(400, "role must be 'user' or 'admin'")

    loop = asyncio.get_event_loop()
    updated = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_update_user, user_id, patch)
    if not updated:
        raise HandlerError(404, "User not found")
    return updated


@register("user.delete")
async def user_delete(params: dict, context: dict) -> dict:
    user_id = params.get("user_id")
    if not user_id:
        raise HandlerError(400, "user_id required")
    if user_id == context.get("user_id"):
        raise HandlerError(400, "Cannot delete your own account")

    loop = asyncio.get_event_loop()
    deleted = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_delete_user, user_id)
    if not deleted:
        raise HandlerError(404, "User not found")
    return {"deleted": user_id}


@register("system.stats")
async def system_stats(params: dict, context: dict) -> dict:
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
