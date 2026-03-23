"""
GPU task scheduler — Slurm-inspired fair-share + backfill.

Modes:
  Legacy (cluster.enabled=false):
    Runs as a synchronous tick in a thread executor. Launches local subprocesses
    for build tasks and signals asyncio.Events for search tasks.

  Cluster (cluster.enabled=true):
    Runs as an async loop. Queries available workers from WorkerRegistry,
    uses affinity routing, and dispatches tasks to remote workers via WorkerClient.
    Task completion is reported back via worker.task_done RPC.

Scheduling algorithm (both modes):
  1. Reap completed/timed-out running tasks
  2. Compute fair-share penalties
  3. Backfill: for each pending task in priority order:
     - Skip if user's running tasks >= quota
     - Skip if no GPU slots available
     - Allocate and launch
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Dict, Optional

from app.core import config_loader


def _cluster_enabled() -> bool:
    return config_loader.get("cluster", "enabled", False)


# ---------------------------------------------------------------------------
# DB helpers (used by both modes)
# ---------------------------------------------------------------------------

def _get_db_pool():
    from app.core.db import get_pool
    return get_pool()


def _blocking_get_pending_tasks() -> list:
    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT gt.id, gt.user_id, gt.task_type, gt.priority, gt.gpu_slots, "
                "gt.dataset_id, gt.search_task_id, u.role "
                "FROM gpu_tasks gt JOIN users u ON u.id = gt.user_id "
                "WHERE gt.status = 'pending' "
                "ORDER BY gt.priority ASC, gt.submitted_at ASC"
            )
            return [
                {
                    "id": str(r[0]), "user_id": str(r[1]), "task_type": r[2],
                    "priority": r[3], "gpu_slots": r[4],
                    "dataset_id": str(r[5]) if r[5] else None,
                    "search_task_id": r[6],
                    "user_role": r[7] or "user",
                }
                for r in cur.fetchall()
            ]
    finally:
        pool.putconn(conn)


def _blocking_get_running_tasks() -> list:
    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, task_type, gpu_slots, dataset_id, search_task_id, "
                "pid, started_at "
                "FROM gpu_tasks WHERE status = 'running'"
            )
            return [
                {
                    "id": str(r[0]), "user_id": str(r[1]), "task_type": r[2],
                    "gpu_slots": r[3],
                    "dataset_id": str(r[4]) if r[4] else None,
                    "search_task_id": r[5],
                    "pid": r[6], "started_at": r[7],
                }
                for r in cur.fetchall()
            ]
    finally:
        pool.putconn(conn)


def _blocking_get_user_quota(user_id: str) -> int:
    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT gpu_quota FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row else 1
    finally:
        pool.putconn(conn)


def _blocking_set_task_running(
    task_id: str,
    pid: Optional[int] = None,
    node_id: Optional[str] = None,
) -> None:
    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE gpu_tasks SET status = 'running', started_at = now(), "
                "pid = %s, assigned_worker = %s WHERE id = %s",
                (pid, node_id, task_id),
            )
            conn.commit()
    finally:
        pool.putconn(conn)


def _blocking_set_task_done(
    task_id: str, gpu_seconds: float, status: str = "done"
) -> None:
    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE gpu_tasks SET status = %s, completed_at = now(), gpu_seconds = %s "
                "WHERE id = %s",
                (status, gpu_seconds, task_id),
            )
            conn.commit()
    finally:
        pool.putconn(conn)


def _blocking_get_dataset_config_path(dataset_id: str) -> Optional[str]:
    from app.core.config import DATASETS_ROOT
    config_path = os.path.join(DATASETS_ROOT, dataset_id, "build_config.json")
    return config_path if os.path.exists(config_path) else None


# ---------------------------------------------------------------------------
# Enqueue helpers (public API)
# ---------------------------------------------------------------------------

def blocking_enqueue_build(dataset_id: str, user_id: str) -> str:
    """Insert a build task into gpu_tasks. Returns gpu_task_id."""
    pool = _get_db_pool()
    conn = pool.getconn()
    base_priority = config_loader.get("scheduler", "build_base_priority", 100)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gpu_tasks (user_id, task_type, priority, dataset_id, gpu_slots) "
                "VALUES (%s, 'build', %s, %s, 1) RETURNING id",
                (user_id, base_priority, dataset_id),
            )
            task_id = str(cur.fetchone()[0])
            conn.commit()
            return task_id
    finally:
        pool.putconn(conn)


def blocking_enqueue_search_task(search_task_id: str, user_id: str, dataset_id: Optional[str]) -> str:
    """Insert a search task into gpu_tasks (cluster mode). Returns gpu_task_id."""
    pool = _get_db_pool()
    conn = pool.getconn()
    base_priority = config_loader.get("scheduler", "search_base_priority", 10)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gpu_tasks (user_id, task_type, priority, search_task_id, dataset_id, gpu_slots) "
                "VALUES (%s, 'search', %s, %s, %s, 1) RETURNING id",
                (user_id, base_priority, search_task_id, dataset_id),
            )
            task_id = str(cur.fetchone()[0])
            conn.commit()
            return task_id
    finally:
        pool.putconn(conn)


# Legacy search enqueue (in-process mode, uses asyncio.Event for slot notification)
_SEARCH_EVENTS: Dict[str, asyncio.Event] = {}
_SEARCH_EVENTS_LOCK = asyncio.Lock()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def enqueue_search_and_wait(search_task_id: str, user_id: str) -> None:
    """[Legacy mode] Enqueue a search GPU task and wait for the scheduler to grant a slot."""
    pool = _get_db_pool()
    conn = pool.getconn()
    base_priority = config_loader.get("scheduler", "search_base_priority", 10)
    timeout = config_loader.get("scheduler", "search_gpu_timeout", 60)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gpu_tasks (user_id, task_type, priority, search_task_id, gpu_slots) "
                "VALUES (%s, 'search', %s, %s, 1) RETURNING id",
                (user_id, base_priority, search_task_id),
            )
            conn.commit()
    finally:
        pool.putconn(conn)

    event = asyncio.Event()
    async with _SEARCH_EVENTS_LOCK:
        _SEARCH_EVENTS[search_task_id] = event
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    finally:
        async with _SEARCH_EVENTS_LOCK:
            _SEARCH_EVENTS.pop(search_task_id, None)


def blocking_release_search_slot(search_task_id: str, user_id: str, gpu_seconds: float):
    """[Legacy mode] Mark search GPU task done and release slot."""
    from .fair_share import blocking_record_gpu_usage
    from .gpu_pool import get_pool

    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE gpu_tasks SET status = 'done', completed_at = now(), gpu_seconds = %s "
                "WHERE search_task_id = %s AND status = 'running'",
                (gpu_seconds, search_task_id),
            )
            cur.execute(
                "SELECT id FROM gpu_tasks WHERE search_task_id = %s", (search_task_id,)
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                get_pool().release(str(row[0]))
    finally:
        pool.putconn(conn)
    blocking_record_gpu_usage(user_id, gpu_seconds)


# ---------------------------------------------------------------------------
# Queue inspection helpers (unchanged)
# ---------------------------------------------------------------------------

def blocking_get_queue_for_user(user_id: str) -> list:
    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, task_type, status, priority, gpu_slots, dataset_id, "
                "search_task_id, submitted_at, started_at, completed_at, gpu_seconds "
                "FROM gpu_tasks WHERE user_id = %s "
                "ORDER BY submitted_at DESC LIMIT 50",
                (user_id,),
            )
            return [_task_row(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


def blocking_get_full_queue() -> list:
    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT gt.id, gt.user_id, u.username, gt.task_type, gt.status, gt.priority, "
                "gt.gpu_slots, gt.dataset_id, gt.search_task_id, gt.submitted_at, "
                "gt.started_at, gt.completed_at, gt.gpu_seconds "
                "FROM gpu_tasks gt JOIN users u ON u.id = gt.user_id "
                "WHERE gt.status IN ('pending', 'running') "
                "ORDER BY gt.priority ASC, gt.submitted_at ASC"
            )
            rows = cur.fetchall()
            return [
                {
                    "id": str(r[0]), "user_id": str(r[1]), "username": r[2],
                    "task_type": r[3], "status": r[4], "priority": r[5],
                    "gpu_slots": r[6],
                    "dataset_id": str(r[7]) if r[7] else None,
                    "search_task_id": r[8],
                    "submitted_at": r[9].isoformat() if r[9] else None,
                    "started_at": r[10].isoformat() if r[10] else None,
                    "completed_at": r[11].isoformat() if r[11] else None,
                    "gpu_seconds": r[12],
                }
                for r in rows
            ]
    finally:
        pool.putconn(conn)


def blocking_cancel_task(task_id: str) -> bool:
    pool = _get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE gpu_tasks SET status = 'cancelled' WHERE id = %s AND status = 'pending' "
                "RETURNING id",
                (task_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return row is not None
    finally:
        pool.putconn(conn)


def _task_row(r) -> dict:
    return {
        "id": str(r[0]), "task_type": r[1], "status": r[2], "priority": r[3],
        "gpu_slots": r[4],
        "dataset_id": str(r[5]) if r[5] else None,
        "search_task_id": r[6],
        "submitted_at": r[7].isoformat() if r[7] else None,
        "started_at": r[8].isoformat() if r[8] else None,
        "completed_at": r[9].isoformat() if r[9] else None,
        "gpu_seconds": r[10],
    }


# ---------------------------------------------------------------------------
# Legacy build process registry
# ---------------------------------------------------------------------------

_BUILD_PROCS: Dict[str, subprocess.Popen] = {}


def _set_search_event(search_task_id: str, gpu_task_id: str):
    event = _SEARCH_EVENTS.get(search_task_id)
    if event:
        event.set()


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class GpuScheduler:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._start_times: Dict[str, float] = {}

    def start(self):
        self._running = True
        if _cluster_enabled():
            self._task = asyncio.create_task(self._cluster_loop())
            print("[scheduler] Cluster GPU scheduler started")
        else:
            self._task = asyncio.create_task(self._legacy_loop())
            print("[scheduler] Legacy GPU scheduler started")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        # Terminate legacy build subprocesses
        for dataset_id, proc in list(_BUILD_PROCS.items()):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        _BUILD_PROCS.clear()
        print("[scheduler] GPU scheduler stopped")

    # ------------------------------------------------------------------
    # Legacy mode (single-node in-process execution)
    # ------------------------------------------------------------------

    async def _legacy_loop(self):
        poll_interval = config_loader.get("scheduler", "poll_interval", 0.5)
        while self._running:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._legacy_tick)
            except Exception as e:
                print(f"[scheduler] legacy tick error: {e}")
            await asyncio.sleep(poll_interval)

    def _legacy_tick(self):
        from .gpu_pool import get_pool as get_gpu_pool
        from .fair_share import (
            blocking_get_decayed_usage, blocking_record_gpu_usage, compute_fair_share_penalty
        )

        gpu_pool = get_gpu_pool()
        search_timeout = config_loader.get("scheduler", "search_gpu_timeout", 60)
        build_timeout = config_loader.get("scheduler", "build_gpu_timeout", 86400)

        running = _blocking_get_running_tasks()
        for task in running:
            task_id = task["id"]
            elapsed = time.time() - self._start_times.get(task_id, time.time())
            finished = failed = False

            if task["task_type"] == "build":
                proc = _BUILD_PROCS.get(task["dataset_id"])
                if proc and proc.poll() is not None:
                    failed = proc.returncode != 0
                    finished = True
                    _BUILD_PROCS.pop(task["dataset_id"], None)
                elif elapsed > build_timeout:
                    finished = True
            elif task["task_type"] == "search":
                if elapsed > search_timeout:
                    finished = True

            if finished:
                status = "failed" if failed else "done"
                _blocking_set_task_done(task_id, elapsed, status)
                gpu_pool.release(task_id)
                self._start_times.pop(task_id, None)
                blocking_record_gpu_usage(task["user_id"], elapsed * task["gpu_slots"])

        usage_map = blocking_get_decayed_usage()
        running_now = _blocking_get_running_tasks()
        user_running_count: Dict[str, int] = {}
        for t in running_now:
            user_running_count[t["user_id"]] = user_running_count.get(t["user_id"], 0) + 1

        pending = _blocking_get_pending_tasks()
        for task in pending:
            user_id = task["user_id"]
            task_id = task["id"]

            quota = _blocking_get_user_quota(user_id)
            if quota > 0 and user_running_count.get(user_id, 0) >= quota:
                continue
            if not gpu_pool.allocate(task_id, task["gpu_slots"]):
                continue

            self._start_times[task_id] = time.time()
            user_running_count[user_id] = user_running_count.get(user_id, 0) + 1

            if task["task_type"] == "build":
                self._legacy_launch_build(task)
            else:
                self._legacy_launch_search(task)

    def _legacy_launch_build(self, task: dict):
        dataset_id = task["dataset_id"]
        config_path = _blocking_get_dataset_config_path(dataset_id)
        if not config_path:
            _blocking_set_task_done(task["id"], 0, "failed")
            from .gpu_pool import get_pool
            get_pool().release(task["id"])
            return
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.build.worker", "--config", config_path],
            cwd=_PROJECT_ROOT,
        )
        _BUILD_PROCS[dataset_id] = proc
        _blocking_set_task_running(task["id"], pid=proc.pid)

    def _legacy_launch_search(self, task: dict):
        search_task_id = task["search_task_id"]
        _blocking_set_task_running(task["id"])
        asyncio.get_event_loop().call_soon_threadsafe(
            _set_search_event, search_task_id, task["id"]
        )

    # ------------------------------------------------------------------
    # Cluster mode (multi-node worker dispatch)
    # ------------------------------------------------------------------

    async def _cluster_loop(self):
        poll_interval = config_loader.get("scheduler", "poll_interval", 0.5)
        while self._running:
            try:
                await self._cluster_tick()
            except Exception as e:
                print(f"[scheduler] cluster tick error: {e}")
            await asyncio.sleep(poll_interval)

    async def _cluster_tick(self):
        from .worker_registry import get_registry
        from .cluster_pool import get_cluster_pool
        from .fair_share import blocking_get_decayed_usage, blocking_record_gpu_usage
        from .affinity import select_worker_for_search, select_worker_for_build

        loop = asyncio.get_event_loop()
        pool = get_cluster_pool()
        registry = get_registry()

        # Step 1: Check liveness and reap timed-out tasks
        await registry.check_liveness()
        build_timeout = config_loader.get("scheduler", "build_gpu_timeout", 86400)
        search_timeout = config_loader.get("scheduler", "search_gpu_timeout", 60)

        running = await loop.run_in_executor(None, _blocking_get_running_tasks)
        for task in running:
            task_id = task["id"]
            elapsed = time.time() - self._start_times.get(task_id, time.time())
            timeout = build_timeout if task["task_type"] == "build" else search_timeout
            if elapsed > timeout:
                await loop.run_in_executor(None, _blocking_set_task_done, task_id, elapsed, "failed")
                pool.release(task_id)
                self._start_times.pop(task_id, None)
                await loop.run_in_executor(
                    None, blocking_record_gpu_usage, task["user_id"], elapsed
                )

        # Step 2: Get scheduling state
        usage_map = await loop.run_in_executor(None, blocking_get_decayed_usage)
        running_now = await loop.run_in_executor(None, _blocking_get_running_tasks)
        user_running_count: Dict[str, int] = {}
        for t in running_now:
            user_running_count[t["user_id"]] = user_running_count.get(t["user_id"], 0) + 1

        online_workers = await registry.get_online_workers(include_hidden=True)
        if not online_workers:
            return  # No workers available; will retry next tick

        # Step 3: Backfill pending tasks
        pending = await loop.run_in_executor(None, _blocking_get_pending_tasks)

        for task in pending:
            user_id = task["user_id"]
            task_id = task["id"]
            dataset_id = task.get("dataset_id")
            n_slots = task.get("gpu_slots", 1)
            is_admin = task.get("user_role") == "admin"

            quota = await loop.run_in_executor(None, _blocking_get_user_quota, user_id)
            if quota > 0 and user_running_count.get(user_id, 0) >= quota:
                continue

            if task["task_type"] == "search":
                worker = select_worker_for_search(online_workers, pool, dataset_id, n_slots, is_admin)
            else:
                worker = select_worker_for_build(online_workers, pool, n_slots, is_admin)

            if not worker:
                continue

            allocated_node = pool.allocate(task_id, n_slots, worker.node_id)
            if not allocated_node:
                continue

            self._start_times[task_id] = time.time()
            user_running_count[user_id] = user_running_count.get(user_id, 0) + 1

            if task["task_type"] == "build":
                asyncio.create_task(self._cluster_dispatch_build(task, worker.node_id))
            else:
                asyncio.create_task(self._cluster_dispatch_search(task, worker.node_id))

    async def _cluster_dispatch_search(self, task: dict, node_id: str) -> None:
        from .worker_registry import get_registry
        from .cluster_pool import get_cluster_pool
        from app.core.redis_client import task_get

        loop = asyncio.get_event_loop()
        registry = get_registry()
        pool = get_cluster_pool()
        task_id = task["id"]
        search_task_id = task["search_task_id"]

        worker = await registry.get_worker(node_id)
        if not worker or not worker.client or not worker.client.is_connected:
            await loop.run_in_executor(None, _blocking_set_task_done, task_id, 0, "failed")
            pool.release(task_id)
            self._start_times.pop(task_id, None)
            print(f"[scheduler] Worker {node_id} unavailable for search {task_id}")
            return

        task_data = await task_get(search_task_id)
        if not task_data:
            await loop.run_in_executor(None, _blocking_set_task_done, task_id, 0, "failed")
            pool.release(task_id)
            self._start_times.pop(task_id, None)
            print(f"[scheduler] Search params not in Redis for task {search_task_id}")
            return

        await loop.run_in_executor(None, _blocking_set_task_running, task_id, None, node_id)

        try:
            await worker.client.dispatch_search(
                search_task_id,
                {
                    "gpu_task_id": task_id,
                    "sequence": task_data["sequence"],
                    "top_k": task_data.get("top_k", 5),
                    "pooling": task_data.get("pooling", "mean"),
                    "db_table": task_data.get("db_table", ""),
                    "dataset_id": task_data.get("dataset_id"),
                    "index_dir": task_data.get("index_dir"),
                    "user_id": task_data.get("user_id"),
                },
            )
        except Exception as e:
            print(f"[scheduler] dispatch_search to {node_id} failed: {e}")
            await loop.run_in_executor(None, _blocking_set_task_done, task_id, 0, "failed")
            pool.release(task_id)
            self._start_times.pop(task_id, None)
            from app.daemon.worker_client import WorkerUnreachableError
            if isinstance(e, WorkerUnreachableError):
                from app.daemon.operations.worker_ops import deregister_unreachable_worker
                asyncio.create_task(deregister_unreachable_worker(node_id))

    async def _cluster_dispatch_build(self, task: dict, node_id: str) -> None:
        from .worker_registry import get_registry
        from .cluster_pool import get_cluster_pool

        loop = asyncio.get_event_loop()
        registry = get_registry()
        pool = get_cluster_pool()
        task_id = task["id"]

        worker = await registry.get_worker(node_id)
        if not worker or not worker.client or not worker.client.is_connected:
            await loop.run_in_executor(None, _blocking_set_task_done, task_id, 0, "failed")
            pool.release(task_id)
            self._start_times.pop(task_id, None)
            return

        config_path = _blocking_get_dataset_config_path(task["dataset_id"])
        if not config_path:
            await loop.run_in_executor(None, _blocking_set_task_done, task_id, 0, "failed")
            pool.release(task_id)
            self._start_times.pop(task_id, None)
            return

        with open(config_path, "r", encoding="utf-8") as f:
            build_config = json.load(f)
        build_config["user_id"] = task["user_id"]  # pass for task_done accounting

        await loop.run_in_executor(None, _blocking_set_task_running, task_id, None, node_id)

        try:
            await worker.client.dispatch_build(task_id, build_config)
        except Exception as e:
            print(f"[scheduler] dispatch_build to {node_id} failed: {e}")
            await loop.run_in_executor(None, _blocking_set_task_done, task_id, 0, "failed")
            pool.release(task_id)
            self._start_times.pop(task_id, None)
            from app.daemon.worker_client import WorkerUnreachableError
            if isinstance(e, WorkerUnreachableError):
                from app.daemon.operations.worker_ops import deregister_unreachable_worker
                asyncio.create_task(deregister_unreachable_worker(node_id))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_scheduler: Optional[GpuScheduler] = None


def get_scheduler() -> Optional[GpuScheduler]:
    return _scheduler


def init_scheduler() -> GpuScheduler:
    global _scheduler
    _scheduler = GpuScheduler()
    return _scheduler
