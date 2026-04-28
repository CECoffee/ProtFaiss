"""
Task management: submit, query, remove search tasks.

In cluster mode (cluster.enabled=true):
  - Task params are stored in Redis with a TTL
  - Execution is dispatched to a worker node via the GPU scheduler
  - Workers write results back to Redis via task_update_fields()

In legacy mode (cluster.enabled=false):
  - Tasks run as in-process background asyncio coroutines
  - Results are stored in Redis (same retrieval path for both modes)
  - The in-process path waits for a GPU slot from the scheduler before executing
"""
import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.core import config_loader
from app.core.redis_client import task_set, task_get, task_delete, task_update_fields, TASK_TTL
from app.search.history_db import blocking_save_search_hits
from .config import THREADPOOL_WORKERS, MAX_CONCURRENT_ENCODINGS

BLOCKING_EXECUTOR = ThreadPoolExecutor(max_workers=THREADPOOL_WORKERS)
ENCODE_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_ENCODINGS)


def _cluster_enabled() -> bool:
    return config_loader.get("cluster", "enabled", False)


async def submit_task(
    sequence: str,
    top_k: int = 5,
    pooling: str = "mean",
    db_table: str = "",
    user_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
) -> str:
    task_id = str(uuid.uuid4())
    data = {
        "status": "pending",
        "index_status": "checking",
        "result": None,
        "error": None,
        "created_at": time.time(),
        "user_id": user_id,
        # Search params stored for worker dispatch in cluster mode
        "sequence": sequence,
        "top_k": top_k,
        "pooling": pooling,
        "db_table": db_table,
        "dataset_id": dataset_id,
    }
    await task_set(task_id, data)

    if _cluster_enabled():
        from app.scheduler.scheduler import blocking_enqueue_search_task
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            BLOCKING_EXECUTOR,
            blocking_enqueue_search_task,
            task_id, user_id, dataset_id,
        )
    else:
        asyncio.create_task(
            _legacy_background_task(task_id, sequence, top_k, pooling, db_table, dataset_id, user_id)
        )

    return task_id


async def _legacy_background_task(
    task_id: str,
    sequence: str,
    top_k: int,
    pooling: str,
    db_table: str,
    dataset_id: Optional[str],
    user_id: Optional[str] = None,
) -> None:
    """In-process execution path for single-node (legacy) mode."""
    from app.core.encoder import clean_sequence, blocking_encode
    from app.search.retriever import blocking_faiss_search, is_cached
    from app.search.db_queries import blocking_db_get_rows_from_table
    from app.search import vram_timer
    from app.scheduler.scheduler import enqueue_search_and_wait, blocking_release_search_slot

    loop = asyncio.get_event_loop()
    start_time = time.time()

    try:
        cleaned = clean_sequence(sequence)
        if not cleaned:
            raise ValueError("sequence empty after cleaning")

        # Wait for a GPU slot from the scheduler
        await enqueue_search_and_wait(task_id, user_id)

        async with ENCODE_SEMAPHORE:
            qvec = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_encode, cleaned, pooling)
        esm_time = time.time()

        already_cached = dataset_id and is_cached(dataset_id)
        await task_update_fields(task_id, {"index_status": "ready" if already_cached else "loading"})

        index_start = time.time()
        merged, load_seconds = await loop.run_in_executor(
            BLOCKING_EXECUTOR, blocking_faiss_search, qvec, top_k, None, dataset_id
        )
        faiss_done = time.time()

        await task_update_fields(task_id, {"index_status": "ready"})

        ids = [r[1] for r in merged]
        rows = []
        if ids:
            rows = await loop.run_in_executor(
                BLOCKING_EXECUTOR, blocking_db_get_rows_from_table, db_table, ids
            )
        db_time = time.time()

        rows_map = {row[0]: row for row in rows}
        out = []
        for dist, rid in merged:
            row = rows_map.get(rid)
            if row:
                out.append({
                    "id": int(row[0]),
                    "header": row[1],
                    "sequence": row[2],
                    "ph": row[3],
                    "ko": row[4],
                    "ec": row[5],
                    "faiss_distance": float(dist),
                })
            else:
                out.append({"id": rid, "faiss_distance": float(dist), "note": "db miss"})

        await task_update_fields(task_id, {
            "status": "done",
            "result": out,
            "times": {
                "total_time": db_time - start_time,
                "esm_time": esm_time - start_time,
                "index_load_time": load_seconds if not already_cached else 0.0,
                "faiss_time": (faiss_done - index_start) - load_seconds,
                "db_time": db_time - faiss_done,
            },
        })

        if user_id and dataset_id:
            await vram_timer.reset_timer(user_id, dataset_id)

        # Release the GPU slot
        gpu_seconds = time.time() - start_time
        await loop.run_in_executor(
            BLOCKING_EXECUTOR, blocking_release_search_slot, task_id, user_id, gpu_seconds
        )

        # Persist hits to DB after GPU resources are released
        await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_save_search_hits, task_id, out)

    except Exception as e:
        await task_update_fields(task_id, {"status": "error", "error": str(e)})
        print(f"[tasks] background task error: {e}")


async def get_task(task_id: str) -> Optional[dict]:
    data = await task_get(task_id)
    if not data:
        return None
    return {
        "task_id": task_id,
        "status": data.get("status", "pending"),
        "index_status": data.get("index_status", "unknown"),
        "result": data.get("result"),
        "times": data.get("times"),
        "error": data.get("error"),
        "user_id": data.get("user_id"),
    }


async def remove_task(task_id: str) -> None:
    await task_delete(task_id)
