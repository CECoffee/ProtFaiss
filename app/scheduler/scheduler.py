"""
GPU task scheduler — Slurm-inspired fair-share + backfill.

Scheduling loop (runs every poll_interval seconds):
1. Reap completed tasks (update DB, release GPU slots, record usage)
2. Compute fair-share penalties for all users
3. Sort pending tasks by effective_priority = base_priority + fair_share_penalty
4. Backfill: for each pending task (in priority order):
   - Skip if user's running tasks >= user.gpu_quota
   - Skip if available GPU slots < task.gpu_slots
   - Allocate slots and launch task
"""
import asyncio
import subprocess
import sys
import os
import time
from typing import Dict, Optional

from .gpu_pool import get_pool as get_gpu_pool
from .fair_share import (
    blocking_get_decayed_usage, blocking_record_gpu_usage, compute_fair_share_penalty
)
from app.core.db import get_pool as get_db_pool
from app.core import config_loader

# search_task_id → asyncio.Event (set when GPU slot is granted)
_SEARCH_EVENTS: Dict[str, asyncio.Event] = {}
_SEARCH_EVENTS_LOCK = asyncio.Lock()

# dataset_id → subprocess.Popen
_BUILD_PROCS: Dict[str, subprocess.Popen] = {}

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _blocking_get_pending_tasks() -> list:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, task_type, priority, gpu_slots, dataset_id, search_task_id "
                "FROM gpu_tasks WHERE status = 'pending' "
                "ORDER BY priority ASC, submitted_at ASC"
            )
            return [
                {
                    "id": str(r[0]), "user_id": str(r[1]), "task_type": r[2],
                    "priority": r[3], "gpu_slots": r[4],
                    "dataset_id": str(r[5]) if r[5] else None,
                    "search_task_id": r[6],
                }
                for r in cur.fetchall()
            ]
    finally:
        pool.putconn(conn)


def _blocking_get_running_tasks() -> list:
    pool = get_db_pool()
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
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT gpu_quota FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row else 1
    finally:
        pool.putconn(conn)


def _blocking_set_task_running(task_id: str, pid: Optional[int] = None) -> None:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE gpu_tasks SET status = 'running', started_at = now(), pid = %s WHERE id = %s",
                (pid, task_id),
            )
            conn.commit()
    finally:
        pool.putconn(conn)


def _blocking_set_task_done(task_id: str, gpu_seconds: float, status: str = "done") -> None:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE gpu_tasks SET status = %s, completed_at = now(), gpu_seconds = %s WHERE id = %s",
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
# Scheduler
# ---------------------------------------------------------------------------

class GpuScheduler:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # task_id → start_time (for GPU seconds accounting)
        self._start_times: Dict[str, float] = {}

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        print("[scheduler] GPU scheduler started")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        # Terminate all build subprocesses
        for dataset_id, proc in list(_BUILD_PROCS.items()):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        _BUILD_PROCS.clear()
        print("[scheduler] GPU scheduler stopped")

    async def _loop(self):
        poll_interval = config_loader.get("scheduler", "poll_interval", 0.5)
        while self._running:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._tick)
            except Exception as e:
                print(f"[scheduler] tick error: {e}")
            await asyncio.sleep(poll_interval)

    def _tick(self):
        gpu_pool = get_gpu_pool()
        search_timeout = config_loader.get("scheduler", "search_gpu_timeout", 60)
        build_timeout = config_loader.get("scheduler", "build_gpu_timeout", 86400)

        # --- Step 1: Reap completed/timed-out running tasks ---
        running = _blocking_get_running_tasks()
        for task in running:
            task_id = task["id"]
            task_type = task["task_type"]
            elapsed = time.time() - (self._start_times.get(task_id, time.time()))

            finished = False
            failed = False

            if task_type == "build":
                pid = task.get("pid")
                if pid:
                    proc = _BUILD_PROCS.get(task["dataset_id"])
                    if proc and proc.poll() is not None:
                        failed = proc.returncode != 0
                        finished = True
                        _BUILD_PROCS.pop(task["dataset_id"], None)
                elif elapsed > build_timeout:
                    finished = True

            elif task_type == "search":
                # Search tasks are short-lived; mark done if timed out
                if elapsed > search_timeout:
                    finished = True

            if finished:
                gpu_seconds = elapsed
                status = "failed" if failed else "done"
                _blocking_set_task_done(task_id, gpu_seconds, status)
                gpu_pool.release(task_id)
                self._start_times.pop(task_id, None)
                # Record fair-share usage
                blocking_record_gpu_usage(task["user_id"], gpu_seconds * task["gpu_slots"])

        # --- Step 2: Compute fair-share penalties ---
        usage_map = blocking_get_decayed_usage()

        # --- Step 3: Count running tasks per user ---
        running_now = _blocking_get_running_tasks()
        user_running_count: Dict[str, int] = {}
        for t in running_now:
            user_running_count[t["user_id"]] = user_running_count.get(t["user_id"], 0) + 1

        # --- Step 4: Backfill scheduling ---
        pending = _blocking_get_pending_tasks()
        search_base = config_loader.get("scheduler", "search_base_priority", 10)
        build_base = config_loader.get("scheduler", "build_base_priority", 100)

        for task in pending:
            user_id = task["user_id"]
            task_id = task["id"]

            # Compute effective priority
            base = search_base if task["task_type"] == "search" else build_base
            penalty = compute_fair_share_penalty(user_id, usage_map)
            # (effective priority is used for ordering, already sorted from DB)

            # Check user quota
            quota = _blocking_get_user_quota(user_id)
            running_count = user_running_count.get(user_id, 0)
            if running_count >= quota:
                continue

            # Check GPU slots
            if not gpu_pool.allocate(task_id, task["gpu_slots"]):
                continue

            # Launch task
            self._start_times[task_id] = time.time()
            user_running_count[user_id] = running_count + 1

            if task["task_type"] == "build":
                self._launch_build(task)
            else:
                self._launch_search(task)

    def _launch_build(self, task: dict):
        dataset_id = task["dataset_id"]
        config_path = _blocking_get_dataset_config_path(dataset_id)
        if not config_path:
            _blocking_set_task_done(task["id"], 0, "failed")
            get_gpu_pool().release(task["id"])
            return

        proc = subprocess.Popen(
            [sys.executable, "-m", "app.build.worker", "--config", config_path],
            cwd=_PROJECT_ROOT,
        )
        _BUILD_PROCS[dataset_id] = proc
        _blocking_set_task_running(task["id"], pid=proc.pid)

    def _launch_search(self, task: dict):
        # Signal the waiting search coroutine via asyncio.Event
        search_task_id = task["search_task_id"]
        _blocking_set_task_running(task["id"])
        # Schedule event.set() on the event loop
        asyncio.get_event_loop().call_soon_threadsafe(
            _set_search_event, search_task_id, task["id"]
        )


def _set_search_event(search_task_id: str, gpu_task_id: str):
    """Called from scheduler thread to wake up a waiting search coroutine."""
    event = _SEARCH_EVENTS.get(search_task_id)
    if event:
        event.set()


# Module-level singleton
_scheduler: Optional[GpuScheduler] = None


def get_scheduler() -> GpuScheduler:
    return _scheduler


def init_scheduler() -> GpuScheduler:
    global _scheduler
    _scheduler = GpuScheduler()
    return _scheduler


# ---------------------------------------------------------------------------
# Public API for enqueuing tasks
# ---------------------------------------------------------------------------

def blocking_enqueue_build(dataset_id: str, user_id: str) -> str:
    """Insert a build task into gpu_tasks. Returns gpu_task_id."""
    pool = get_db_pool()
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


async def enqueue_search_and_wait(search_task_id: str, user_id: str) -> None:
    """
    Enqueue a search GPU task and wait until the scheduler grants a slot.
    Raises asyncio.TimeoutError if not granted within search_gpu_timeout.
    """
    pool = get_db_pool()
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
            gpu_task_id = str(cur.fetchone()[0])
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
    """Mark search GPU task as done and release the slot."""
    pool = get_db_pool()
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
                get_gpu_pool().release(str(row[0]))
    finally:
        pool.putconn(conn)
    blocking_record_gpu_usage(user_id, gpu_seconds)


def blocking_get_queue_for_user(user_id: str) -> list:
    pool = get_db_pool()
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
    pool = get_db_pool()
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
    pool = get_db_pool()
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
