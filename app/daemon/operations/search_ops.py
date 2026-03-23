"""
Search operations: submit a search task and retrieve its result.
Wraps app.search.tasks — the daemon owns the task store and executor.
"""
import asyncio

from app.daemon.handler import register, HandlerError
from app.search.tasks import submit_task, get_task, remove_task, BLOCKING_EXECUTOR
from app.build.dataset_db import blocking_get_user_active_id, blocking_get_dataset


@register("search.submit")
async def search_submit(params: dict, context: dict) -> dict:
    sequence = params.get("sequence", "").strip()
    if not sequence:
        raise HandlerError(400, "sequence required")

    from app.core import config_loader
    if config_loader.get("cluster", "enabled", False):
        from app.scheduler.cluster_pool import get_cluster_pool
        if get_cluster_pool().total_slots == 0:
            raise HandlerError(503, "No GPU workers online. Search is unavailable.")

    user_id = context.get("user_id")
    loop = asyncio.get_event_loop()

    # Resolve active dataset if not explicitly provided
    dataset_id = params.get("dataset_id")
    index_dir = params.get("index_dir")
    db_table = params.get("db_table")

    if not dataset_id:
        active_id = await loop.run_in_executor(
            BLOCKING_EXECUTOR, blocking_get_user_active_id, user_id
        )
        if active_id is None:
            raise HandlerError(409, "No dataset is active. Please activate a dataset before searching.")
        dataset_id = active_id

    if not db_table or not index_dir:
        entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
        if entry is None or entry.get("status") != "ready":
            raise HandlerError(409, "Active dataset is not ready.")
        db_table = entry["db_table"]
        index_dir = entry["index_dir"]

    task_id = await submit_task(
        sequence,
        params.get("top_k", 5),
        params.get("pooling", "mean"),
        db_table,
        user_id=user_id,
        dataset_id=dataset_id,
        index_dir=index_dir,
    )
    return {"task_id": task_id}


@register("search.result")
async def search_result(params: dict, context: dict) -> dict:
    task_id = params.get("task_id")
    if not task_id:
        raise HandlerError(400, "task_id required")

    task = await get_task(task_id)
    if not task:
        raise HandlerError(404, "task not found")

    user_id = context.get("user_id")
    role = context.get("role", "user")
    if task.get("user_id") != user_id and role != "admin":
        raise HandlerError(403, "Access denied")

    if task["status"] == "done":
        remove_task(task_id)

    return task
