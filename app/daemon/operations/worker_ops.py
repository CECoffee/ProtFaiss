"""
Control-plane handlers for worker node lifecycle RPCs.

Workers connect to the control plane's IPC port (9812) and call:
  worker.register   — announce presence, provide address for WorkerClient
  worker.heartbeat  — update liveness and cached-dataset list
  worker.task_done  — report task completion (releases GPU slot)

These methods are accessible from any connection (no role check needed
since they carry {"role": "system"} context set by the worker).
"""
import asyncio

from app.daemon.handler import register
from app.scheduler.worker_registry import get_registry
from app.scheduler.cluster_pool import get_cluster_pool
from app.scheduler.fair_share import blocking_record_gpu_usage


@register("worker.register")
async def worker_register(params: dict, context: dict) -> dict:
    node_id = params.get("node_id", "")
    address = params.get("address", "")
    gpu_count = params.get("gpu_count", 1)
    gpu_slots = params.get("gpu_slots", 1)
    capabilities = params.get("capabilities", ["encode", "search", "build"])

    if not node_id or not address:
        return {"error": "node_id and address are required"}

    registry = get_registry()
    await registry.register(node_id, address, gpu_count, gpu_slots, capabilities)

    # Register slots in ClusterGpuPool
    pool = get_cluster_pool()
    pool.register_node(node_id, gpu_slots)

    # Open a reverse WorkerClient connection to the worker
    asyncio.create_task(_connect_to_worker(node_id, address))

    return {"ok": True, "node_id": node_id}


@register("worker.heartbeat")
async def worker_heartbeat(params: dict, context: dict) -> dict:
    node_id = params.get("node_id", "")
    cached_datasets = params.get("cached_datasets", [])
    running_tasks = params.get("running_tasks", 0)
    metrics = params.get("metrics", {})

    registry = get_registry()
    worker = await registry.get_worker(node_id)
    if worker is None:
        # Worker is unknown — control plane may have restarted; signal re-registration
        return {"ok": True, "registered": False}

    await registry.heartbeat(node_id, cached_datasets, running_tasks, metrics)
    return {"ok": True, "registered": True}


@register("worker.task_done")
async def worker_task_done(params: dict, context: dict) -> dict:
    gpu_task_id = params.get("gpu_task_id", "")
    gpu_seconds = float(params.get("gpu_seconds", 0.0))
    user_id = params.get("user_id")
    status = params.get("status", "done")

    if not gpu_task_id:
        return {"error": "gpu_task_id required"}

    loop = asyncio.get_event_loop()

    # Update gpu_tasks status in DB
    from app.scheduler.scheduler import (
        _blocking_set_task_done, get_scheduler
    )
    await loop.run_in_executor(
        None, _blocking_set_task_done, gpu_task_id, gpu_seconds, status
    )

    # Release GPU slot in cluster pool
    pool = get_cluster_pool()
    pool.release(gpu_task_id)

    # Record fair-share usage
    if user_id:
        await loop.run_in_executor(
            None, blocking_record_gpu_usage, user_id, gpu_seconds
        )

    # Clean up scheduler start-time tracking
    scheduler = get_scheduler()
    if scheduler:
        scheduler._start_times.pop(gpu_task_id, None)

    return {"ok": True}


@register("worker.deregister")
async def worker_deregister(params: dict, context: dict) -> dict:
    node_id = params.get("node_id", "")
    if not node_id:
        return {"error": "node_id required"}

    registry = get_registry()
    await registry.deregister(node_id)
    return {"ok": True}


async def deregister_unreachable_worker(node_id: str) -> None:
    """Deregister a worker that cannot be reached after all retries are exhausted."""
    registry = get_registry()
    await registry.deregister(node_id)
    print(f"[worker_ops] Worker {node_id} deregistered due to unreachability")


async def _connect_to_worker(node_id: str, address: str) -> None:
    """Establish a persistent WorkerClient connection to a newly registered worker.

    Retries up to retry_num times (from config) with exponential backoff.
    If all retries are exhausted the worker is automatically deregistered.
    """
    from app.daemon.worker_client import WorkerClient
    from app.scheduler.worker_registry import get_registry
    from app.core import config_loader

    retry_num = config_loader.get("cluster", "retry_num", 3)
    host, port_str = address.rsplit(":", 1)
    port = int(port_str)

    for attempt in range(retry_num + 1):
        try:
            client = WorkerClient(node_id, host, port)
            await client.connect(timeout=15.0)
            registry = get_registry()
            await registry.set_client(node_id, client)
            print(f"[worker_ops] WorkerClient connected to {node_id}")
            return
        except Exception as e:
            if attempt < retry_num:
                delay = min(2 ** attempt, 30)
                print(
                    f"[worker_ops] Failed to connect to {node_id} "
                    f"(attempt {attempt + 1}/{retry_num + 1}): {e}, retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
            else:
                print(
                    f"[worker_ops] Exhausted {retry_num} retries for {node_id}: {e}. "
                    "Deregistering worker."
                )
                await deregister_unreachable_worker(node_id)
