"""
GPU queue and pool operations.
Extracted from app.scheduler.routes.
"""
import asyncio

from app.daemon.handler import register, HandlerError
from app.search.tasks import BLOCKING_EXECUTOR
from app.scheduler.scheduler import blocking_get_queue_for_user, blocking_get_full_queue, blocking_cancel_task
from app.core import gpu as _gpu
from app.core import config_loader


def _pool_snapshot(is_admin: bool = False) -> dict:
    if config_loader.get("cluster", "enabled", False):
        from app.scheduler.cluster_pool import get_cluster_pool
        return get_cluster_pool().snapshot(is_admin=is_admin)
    from app.scheduler.gpu_pool import get_pool
    return get_pool().snapshot()


@register("gpu.queue")
async def gpu_queue(params: dict, context: dict) -> dict:
    user_id = context["user_id"]
    role = context.get("role", "user")
    is_admin = role == "admin"
    loop = asyncio.get_event_loop()

    if is_admin:
        tasks = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_full_queue)
    else:
        tasks = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_queue_for_user, user_id)

    return {"tasks": tasks, "pool": _pool_snapshot(is_admin=is_admin)}


@register("gpu.admin_queue")
async def gpu_admin_queue(params: dict, context: dict) -> dict:
    loop = asyncio.get_event_loop()
    tasks = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_full_queue)
    return {"tasks": tasks, "pool": _pool_snapshot(is_admin=True)}


@register("gpu.cancel")
async def gpu_cancel(params: dict, context: dict) -> dict:
    task_id = params.get("task_id")
    if not task_id:
        raise HandlerError(400, "task_id required")
    loop = asyncio.get_event_loop()
    cancelled = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_cancel_task, task_id)
    if not cancelled:
        raise HandlerError(404, "Task not found or not cancellable")
    return {"cancelled": task_id}


@register("gpu.status")
async def gpu_status(params: dict, context: dict) -> dict:
    is_admin = context.get("role") == "admin"
    return {
        "gpus": _gpu.get_all_gpu_status(),
        "available_devices": _gpu.get_available_devices(),
        "encoding_device": str(_gpu.get_encoding_device()),
        "multi_gpu_enabled": config_loader.get("gpu", "multi_gpu_enabled", True),
        "pool": _pool_snapshot(is_admin=is_admin),
    }
