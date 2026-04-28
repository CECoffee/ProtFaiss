"""
Search operations: submit a search task and retrieve its result.
Wraps app.search.tasks — the daemon owns the task store and executor.
"""
import asyncio

from app.daemon.handler import register, HandlerError
from app.search.tasks import submit_task, get_task, remove_task, BLOCKING_EXECUTOR
from app.build.dataset_db import blocking_get_user_active_id, blocking_get_dataset
from app.search.history_db import blocking_get_search_history, blocking_get_search_hits


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
    db_table = params.get("db_table")

    if not dataset_id:
        active_id = await loop.run_in_executor(
            BLOCKING_EXECUTOR, blocking_get_user_active_id, user_id
        )
        if active_id is None:
            raise HandlerError(409, "No dataset is active. Please activate a dataset before searching.")
        dataset_id = active_id

    if not db_table:
        entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
        if entry is None or entry.get("status") != "ready":
            raise HandlerError(409, "Active dataset is not ready.")
        db_table = entry["db_table"]

    task_id = await submit_task(
        sequence,
        params.get("top_k", 5),
        params.get("pooling", "mean"),
        db_table,
        user_id=user_id,
        dataset_id=dataset_id,
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
        await remove_task(task_id)

    return task


@register("search.history_list")
async def search_history_list(params: dict, context: dict) -> dict:
    user_id = context.get("user_id")
    role = context.get("role", "user")
    limit = int(params.get("limit", 20))
    offset = int(params.get("offset", 0))

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_get_search_history, user_id, role, limit, offset
    )


@register("search.history_detail")
async def search_history_detail(params: dict, context: dict) -> dict:
    search_task_id = params.get("search_task_id")
    if not search_task_id:
        raise HandlerError(400, "search_task_id required")

    user_id = context.get("user_id")
    role = context.get("role", "user")
    loop = asyncio.get_event_loop()

    from app.core.db import get_pool
    pool = get_pool()

    def _fetch_meta_and_hits():
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT gt.user_id, gt.dataset_id, gt.submitted_at, gt.completed_at,
                           gt.gpu_seconds, d.name, d.db_table
                    FROM gpu_tasks gt
                    LEFT JOIN datasets d ON d.id = gt.dataset_id
                    WHERE gt.search_task_id = %s
                    """,
                    (search_task_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None

                task_user_id, dataset_id, submitted_at, completed_at, gpu_seconds, dataset_name, db_table = row

                hits = blocking_get_search_hits(search_task_id, db_table)
                return (task_user_id, dataset_id, submitted_at, completed_at,
                        gpu_seconds, dataset_name, db_table, hits)
        finally:
            pool.putconn(conn)

    result = await loop.run_in_executor(BLOCKING_EXECUTOR, _fetch_meta_and_hits)
    if result is None:
        raise HandlerError(404, "search task not found")

    task_user_id, dataset_id, submitted_at, completed_at, gpu_seconds, dataset_name, db_table, hits = result

    if str(task_user_id) != str(user_id) and role != "admin":
        raise HandlerError(403, "Access denied")

    return {
        "search_task_id": search_task_id,
        "dataset_id": str(dataset_id) if dataset_id else None,
        "dataset_name": dataset_name,
        "submitted_at": submitted_at.isoformat() if submitted_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "gpu_seconds": gpu_seconds,
        "legacy": len(hits) == 0,
        "hits": hits,
    }
