"""
Worker IPC server — handles task dispatch requests from the control plane.

Registered methods:
  worker.search  — execute a search task; result written to Redis
  worker.build   — execute a build task; progress written to DB
  worker.unload  — evict a dataset from the local VRAM cache
  worker.status  — return worker health snapshot

The server uses the same length-prefixed JSON protocol as the daemon.
"""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.core import config_loader
from app.core.redis_client import task_update_fields, TASK_TTL
from app.daemon.protocol import read_message, write_message, make_response
from app.search.config import THREADPOOL_WORKERS

_EXECUTOR = ThreadPoolExecutor(max_workers=THREADPOOL_WORKERS)
_server: Optional[asyncio.Server] = None

# Registered handlers: method → async function
_HANDLERS: dict = {}


def _handle(method: str):
    def decorator(fn):
        _HANDLERS[method] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Handler: search
# ---------------------------------------------------------------------------

@_handle("worker.search")
async def handle_search(params: dict) -> dict:
    """
    Execute a search task and write the result to Redis.
    Returns immediately with {"accepted": true}; execution is async.
    """
    task_id = params["task_id"]
    asyncio.create_task(_run_search(task_id, params))
    return {"accepted": True}


async def _run_search(task_id: str, params: dict) -> None:
    from app.core.encoder import clean_sequence, blocking_encode
    from app.search.retriever import blocking_faiss_search, is_cached
    from app.search.db_queries import blocking_db_get_rows_from_table
    from app.worker.vram_manager import reset_timer

    gpu_task_id = params.get("gpu_task_id")
    sequence = params.get("sequence", "")
    top_k = params.get("top_k", 5)
    pooling = params.get("pooling", "mean")
    db_table = params.get("db_table", "")
    dataset_id = params.get("dataset_id")
    index_dir = params.get("index_dir")
    user_id = params.get("user_id")

    loop = asyncio.get_event_loop()
    start_time = time.time()
    task_status = "done"

    try:
        cleaned = clean_sequence(sequence)
        if not cleaned:
            raise ValueError("sequence empty after cleaning")

        qvec = await loop.run_in_executor(_EXECUTOR, blocking_encode, cleaned, pooling)
        esm_time = time.time()

        already_cached = dataset_id and is_cached(dataset_id)
        await task_update_fields(task_id, {"index_status": "ready" if already_cached else "loading"})

        index_start = time.time()
        merged, load_seconds = await loop.run_in_executor(
            _EXECUTOR, blocking_faiss_search, qvec, top_k, None, dataset_id, index_dir
        )
        faiss_done = time.time()

        await task_update_fields(task_id, {"index_status": "ready"})

        ids = [r[1] for r in merged]
        rows = []
        if ids:
            rows = await loop.run_in_executor(
                _EXECUTOR, blocking_db_get_rows_from_table, db_table, ids
            )
        db_done = time.time()

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

        result_update = {
            "status": "done",
            "result": out,
            "times": {
                "total_time": db_done - start_time,
                "esm_time": esm_time - start_time,
                "index_load_time": load_seconds if not already_cached else 0.0,
                "faiss_time": (faiss_done - index_start) - load_seconds,
                "db_time": db_done - faiss_done,
            },
        }
        await task_update_fields(task_id, result_update)

        if user_id and dataset_id:
            await reset_timer(user_id, dataset_id)

    except Exception as e:
        task_status = "failed"
        await task_update_fields(task_id, {"status": "error", "error": str(e)})
        print(f"[worker] search error task={task_id}: {e}")

    finally:
        gpu_seconds = time.time() - start_time
        if gpu_task_id:
            asyncio.create_task(
                _notify_task_done(gpu_task_id, gpu_seconds, user_id, task_status)
            )


# ---------------------------------------------------------------------------
# Handler: build
# ---------------------------------------------------------------------------

@_handle("worker.build")
async def handle_build(params: dict) -> dict:
    gpu_task_id = params["gpu_task_id"]
    build_config = params["config"]
    asyncio.create_task(_run_build(gpu_task_id, build_config))
    return {"accepted": True}


async def _run_build(gpu_task_id: str, config: dict) -> None:
    from app.build.worker import run_build_job

    loop = asyncio.get_event_loop()
    start_time = time.time()
    user_id = config.get("user_id")
    status = "done"
    try:
        await loop.run_in_executor(_EXECUTOR, run_build_job, config)
    except Exception as e:
        print(f"[worker] build error gpu_task={gpu_task_id}: {e}")
        status = "failed"
    finally:
        gpu_seconds = time.time() - start_time
        asyncio.create_task(_notify_task_done(gpu_task_id, gpu_seconds, user_id, status))


# ---------------------------------------------------------------------------
# Handler: unload
# ---------------------------------------------------------------------------

@_handle("worker.unload")
async def handle_unload(params: dict) -> dict:
    dataset_id = params.get("dataset_id")
    if dataset_id:
        from app.search.retriever import unload_dataset
        from app.worker.vram_manager import cancel_all_for_dataset
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_EXECUTOR, unload_dataset, dataset_id)
        await cancel_all_for_dataset(dataset_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Handler: status
# ---------------------------------------------------------------------------

@_handle("worker.status")
async def handle_status(params: dict) -> dict:
    from app.search.retriever import _CACHE  # internal, for snapshot
    cached = list(_CACHE.keys())
    return {
        "cached_datasets": cached,
        "executor_threads": _EXECUTOR._max_workers,
    }


# ---------------------------------------------------------------------------
# Notify control plane of task completion
# ---------------------------------------------------------------------------

async def _notify_task_done(
    gpu_task_id: str,
    gpu_seconds: float,
    user_id: Optional[str],
    status: str,
) -> None:
    cp_host = config_loader.get("cluster", "control_plane_host", "127.0.0.1")
    cp_port = config_loader.get("cluster", "control_plane_port", 9812)
    try:
        from app.daemon.protocol import read_message, write_message, make_request
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(cp_host, cp_port),
            timeout=10.0,
        )
        req = make_request(
            "worker.task_done",
            {
                "gpu_task_id": gpu_task_id,
                "gpu_seconds": gpu_seconds,
                "user_id": user_id,
                "status": status,
            },
            context={"role": "system"},
        )
        await write_message(writer, req)
        await asyncio.wait_for(read_message(reader), timeout=5.0)
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        print(f"[worker] Failed to notify task_done to control plane: {e}")


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

async def _handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    try:
        while True:
            message = await read_message(reader)
            req_id = message.get("id", "")
            method = message.get("method", "")
            params = message.get("params", {})

            handler = _HANDLERS.get(method)
            if handler is None:
                resp = make_response(req_id, error={"code": 404, "message": f"Unknown method: {method}"})
            else:
                try:
                    result = await handler(params)
                    resp = make_response(req_id, result=result)
                except Exception as e:
                    resp = make_response(req_id, error={"code": 500, "message": str(e)})

            await write_message(writer, resp)
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        print(f"[worker] Connection error from {peer}: {e}")
    finally:
        writer.close()


async def start_worker_server(host: str, port: int) -> asyncio.Server:
    global _server
    _server = await asyncio.start_server(_handle_connection, host, port)
    print(f"[worker] IPC server listening on {host}:{port}")
    asyncio.create_task(_server.serve_forever())
    return _server


async def stop_worker_server() -> None:
    global _server
    if _server:
        _server.close()
        await _server.wait_closed()
        _server = None
