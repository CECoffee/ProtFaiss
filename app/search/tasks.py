import asyncio
import time
import uuid
from typing import Dict, Any, Optional

from concurrent.futures import ThreadPoolExecutor

from .config import THREADPOOL_WORKERS, MAX_CONCURRENT_ENCODINGS
from app.core.encoder import clean_sequence, blocking_encode
from .retriever import blocking_faiss_search, is_cached
from .db_queries import blocking_db_get_rows_from_table
from . import vram_timer

BLOCKING_EXECUTOR = ThreadPoolExecutor(max_workers=THREADPOOL_WORKERS)
ENCODE_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_ENCODINGS)

# in-memory task store
task_store: Dict[str, Dict[str, Any]] = {}
task_store_lock = asyncio.Lock()


async def submit_task(
    sequence: str,
    top_k: int = 5,
    pooling: str = "mean",
    db_table: str = "",
    user_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    index_dir: Optional[str] = None,
) -> str:
    task_id = str(uuid.uuid4())
    async with task_store_lock:
        task_store[task_id] = {
            "status": "pending",
            "index_status": "checking",
            "result": None,
            "error": None,
            "created_at": time.time(),
            "user_id": user_id,
        }
    asyncio.create_task(
        _background_task(task_id, sequence, top_k, pooling, db_table, dataset_id, index_dir, user_id)
    )
    return task_id


async def _background_task(
    task_id: str,
    sequence: str,
    top_k: int,
    pooling: str,
    db_table: str,
    dataset_id: Optional[str],
    index_dir: Optional[str],
    user_id: Optional[str] = None,
):
    loop = asyncio.get_event_loop()
    try:
        cleaned = clean_sequence(sequence)
        if not cleaned:
            raise ValueError("sequence empty after cleaning")

        start_time = time.time()
        async with ENCODE_SEMAPHORE:
            qvec = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_encode, cleaned, pooling)
        esm_time = time.time()

        # Report index loading phase
        already_cached = dataset_id and is_cached(dataset_id)
        async with task_store_lock:
            task_store[task_id]["index_status"] = "ready" if already_cached else "loading"

        index_start = time.time()
        merged = await loop.run_in_executor(
            BLOCKING_EXECUTOR, blocking_faiss_search, qvec, top_k, None, dataset_id, index_dir
        )
        faiss_done = time.time()
        index_load_time = faiss_done - index_start if not already_cached else 0.0

        async with task_store_lock:
            task_store[task_id]["index_status"] = "ready"

        ids = [r[1] for r in merged]
        faiss_time = faiss_done

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
                    "faiss_distance": float(dist)
                })
            else:
                out.append({"id": rid, "faiss_distance": float(dist), "note": "db miss"})

        async with task_store_lock:
            task_store[task_id].update({
                "status": "done",
                "result": out,
                "times": {
                    "total_time": db_time - start_time,
                    "esm_time": esm_time - start_time,
                    "index_load_time": index_load_time,
                    "faiss_time": faiss_time - esm_time,
                    "db_time": db_time - faiss_time,
                },
            })

        # Start/reset idle VRAM release timer for this user
        if user_id and dataset_id:
            await vram_timer.reset_timer(user_id, dataset_id)

    except Exception as e:
        async with task_store_lock:
            task_store[task_id]["status"] = "error"
            task_store[task_id]["error"] = str(e)
        print("background task error:", e)


async def get_task(task_id: str):
    async with task_store_lock:
        task = task_store.get(task_id)
        if not task:
            return None
        return {
            "task_id": task_id,
            "status": task["status"],
            "index_status": task.get("index_status", "unknown"),
            "result": task.get("result"),
            "times": task.get("times"),
            "error": task.get("error"),
            "user_id": task.get("user_id"),
        }


def remove_task(task_id: str):
    task_store.pop(task_id, None)
