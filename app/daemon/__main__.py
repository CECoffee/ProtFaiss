"""
Daemon entry point: python -m app.daemon

Startup sequence (legacy mode, cluster.enabled=false):
  1. Log GPU status
  2. Init ESM2 model
  3. Init DB pool + Redis
  4. Run DB migration + ensure admin user
  5. Init GPU pool
  6. Start GPU scheduler
  7. Mark stale 'building' datasets as error
  8. Write PID file
  9. Start IPC TCP server
 10. Run asyncio event loop until shutdown signal

Startup sequence (cluster mode, cluster.enabled=true):
  Steps 1-2 are SKIPPED (GPU work runs on worker nodes).
  Steps 3-10 run as before, but using ClusterGpuPool + WorkerRegistry instead of
  GpuPool. Workers self-register via IPC after startup.

Shutdown sequence:
  1. Cancel VRAM timers (legacy only)
  2. Stop GPU scheduler
  3. Close DB pool + Redis
  4. Stop IPC server
  5. Remove PID file
"""
import asyncio
import os

from app.core.config import DATASETS_ROOT
from app.core import config_loader
from app.daemon.lifecycle import write_pid, remove_pid, register_signal_handlers
from app.daemon.server import start_server, stop_server


def _cluster_enabled() -> bool:
    return config_loader.get("cluster", "enabled", False)


async def _run():
    from app.core.db import init_db_pool, close_db_pool
    from app.core.redis_client import init_client as init_redis, close_client as close_redis
    from app.auth.init_admin import ensure_admin
    from app.scheduler.scheduler import init_scheduler, get_scheduler
    from app.build.dataset_db import blocking_list_all_datasets, blocking_update_dataset

    cluster = _cluster_enabled()
    print(f"[daemon] Starting up... (mode: {'cluster' if cluster else 'legacy'})")

    if not cluster:
        # Legacy: init GPU + ESM2 on the daemon process itself
        from app.core import gpu as _gpu
        from app.core.encoder import init_model
        from app.core.config import ESM2_MODEL_DIR
        _gpu.log_gpu_status()
        init_model(ESM2_MODEL_DIR)

    init_db_pool()
    await init_redis()
    ensure_admin()

    os.makedirs(DATASETS_ROOT, exist_ok=True)

    if cluster:
        from app.scheduler.cluster_pool import init_cluster_pool
        from app.scheduler.worker_registry import init_registry
        init_cluster_pool()
        init_registry()
        print("[daemon] Cluster GPU pool and worker registry initialized")
    else:
        from app.scheduler.gpu_pool import init_pool
        total_slots = config_loader.get("scheduler", "total_gpu_slots", 4)
        init_pool(total_slots)
        print(f"[daemon] GPU pool initialized with {total_slots} slots")

    scheduler = init_scheduler()
    scheduler.start()

    # Mark stale building/importing datasets as error
    try:
        all_datasets = blocking_list_all_datasets()
        for entry in all_datasets:
            if entry.get("status") in ("building", "importing"):
                blocking_update_dataset(entry["id"], {
                    "status": "error",
                    "error_msg": "Daemon restarted during build",
                    "progress_step": "error",
                })
                print(f"[daemon] Marked stale build {entry['id']} as error")
    except Exception as e:
        print(f"[daemon] Dataset cleanup error: {e}")

    write_pid()

    host = config_loader.get("daemon", "ipc_host", "127.0.0.1")
    port = config_loader.get("daemon", "ipc_port", 9812)
    server = await start_server(host, port)

    stop_event = asyncio.Event()

    def _shutdown():
        stop_event.set()

    register_signal_handlers(_shutdown)

    print("[daemon] Ready. Waiting for connections...")
    await stop_event.wait()

    print("[daemon] Shutting down...")

    if not cluster:
        from app.search import vram_timer
        await vram_timer.cancel_all()

    sched = get_scheduler()
    if sched:
        sched.stop()

    from app.daemon.operations.build_ops import terminate_all_build_processes
    terminate_all_build_processes()

    from app.daemon.operations.export_import_ops import terminate_all_export_import_processes
    terminate_all_export_import_processes()

    close_db_pool()
    await close_redis()
    await stop_server()
    remove_pid()
    print("[daemon] Goodbye.")


if __name__ == "__main__":
    asyncio.run(_run())
