"""
Dataset operations: list, switch, delete, set visibility.
Extracted from app.build.routes.
"""
import asyncio
import os
import shutil

from app.daemon.handler import register, HandlerError
from app.search.tasks import BLOCKING_EXECUTOR
from app.build.dataset_db import (
    blocking_get_dataset, blocking_delete_dataset,
    blocking_list_datasets_for_user, blocking_get_user_active_id,
    blocking_set_user_active_dataset,
)
from app.build.db_operations import blocking_drop_table
from app.core.config import DATASETS_ROOT
from app.search import vram_timer


@register("dataset.list")
async def dataset_list(params: dict, context: dict) -> dict:
    user_id = context["user_id"]
    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_list_datasets_for_user, user_id
    )
    active_id = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_get_user_active_id, user_id
    )
    return {"datasets": entries, "active_dataset_id": active_id}


@register("dataset.switch")
async def dataset_switch(params: dict, context: dict) -> dict:
    dataset_id = params.get("dataset_id")
    if not dataset_id:
        raise HandlerError(400, "dataset_id required")

    user_id = context["user_id"]
    role = context.get("role", "user")
    loop = asyncio.get_event_loop()

    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HandlerError(404, "dataset not found")
    if entry["status"] != "ready":
        raise HandlerError(400, "dataset is not ready")
    if entry["owner_id"] != user_id and entry["visibility"] != "public" and role != "admin":
        raise HandlerError(403, "Access denied")

    await vram_timer.cancel_and_release(user_id)
    await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_set_user_active_dataset, user_id, dataset_id
    )
    return {"active_dataset_id": dataset_id}


@register("dataset.delete")
async def dataset_delete(params: dict, context: dict) -> dict:
    dataset_id = params.get("dataset_id")
    if not dataset_id:
        raise HandlerError(400, "dataset_id required")

    user_id = context["user_id"]
    role = context.get("role", "user")
    loop = asyncio.get_event_loop()

    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HandlerError(404, "dataset not found")
    if entry["owner_id"] != user_id and role != "admin":
        raise HandlerError(403, "Access denied")

    # Terminate active build process if any
    from app.daemon.operations.build_ops import _ACTIVE_BUILD_PROCESSES
    import subprocess
    proc = _ACTIVE_BUILD_PROCESSES.pop(dataset_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    dataset_dir = os.path.join(DATASETS_ROOT, dataset_id)
    if os.path.isdir(dataset_dir):
        shutil.rmtree(dataset_dir, ignore_errors=True)

    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_drop_table, entry["db_table"])
    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_delete_dataset, dataset_id)
    return {"deleted": dataset_id}


@register("dataset.visibility")
async def dataset_visibility(params: dict, context: dict) -> dict:
    dataset_id = params.get("dataset_id")
    visibility = params.get("visibility")
    if visibility not in ("public", "private"):
        raise HandlerError(400, "visibility must be 'public' or 'private'")

    user_id = context["user_id"]
    role = context.get("role", "user")
    loop = asyncio.get_event_loop()

    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HandlerError(404, "dataset not found")
    if entry["owner_id"] != user_id and role != "admin":
        raise HandlerError(403, "Access denied")

    from app.build.dataset_db import blocking_update_dataset
    updated = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_update_dataset, dataset_id, {"visibility": visibility}
    )
    return updated


@register("dataset.get")
async def dataset_get(params: dict, context: dict) -> dict:
    dataset_id = params.get("dataset_id")
    if not dataset_id:
        raise HandlerError(400, "dataset_id required")

    user_id = context["user_id"]
    role = context.get("role", "user")
    loop = asyncio.get_event_loop()

    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HandlerError(404, "dataset not found")
    if entry["owner_id"] != user_id and entry["visibility"] != "public" and role != "admin":
        raise HandlerError(403, "Access denied")
    return entry
