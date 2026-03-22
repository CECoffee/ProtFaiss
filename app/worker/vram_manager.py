"""
Per-user idle VRAM release timer — worker-local version.

After a search completes, reset_timer() starts a countdown for that user.
If the user is idle for time_release_vram seconds, the dataset is evicted
from this worker's FAISS shard cache.

Mirrors the control-plane vram_timer.py but scoped to this worker node.
"""
import asyncio
from typing import Dict

from app.core import config_loader

_user_timers: Dict[str, asyncio.Task] = {}
_user_datasets: Dict[str, str] = {}
_dataset_users: Dict[str, set] = {}
_lock = asyncio.Lock()


async def reset_timer(user_id: str, dataset_id: str) -> None:
    delay = config_loader.get("search", "time_release_vram", 300)
    if not delay or delay <= 0:
        return
    async with _lock:
        _cancel_timer(user_id)
        old = _user_datasets.get(user_id)
        if old and old != dataset_id:
            _unregister_user(user_id, old)
        _dataset_users.setdefault(dataset_id, set()).add(user_id)
        _user_datasets[user_id] = dataset_id
        _user_timers[user_id] = asyncio.create_task(
            _release_after_delay(user_id, dataset_id, delay)
        )


async def cancel_all_for_dataset(dataset_id: str) -> None:
    """Immediately cancel timers for all users referencing this dataset."""
    async with _lock:
        users = list(_dataset_users.get(dataset_id, set()))
        for user_id in users:
            _cancel_timer(user_id)
            _user_datasets.pop(user_id, None)
        _dataset_users.pop(dataset_id, None)


async def cancel_all() -> None:
    async with _lock:
        for t in list(_user_timers.values()):
            t.cancel()
        _user_timers.clear()
        _user_datasets.clear()
        _dataset_users.clear()


def _cancel_timer(user_id: str) -> None:
    t = _user_timers.pop(user_id, None)
    if t and not t.done():
        t.cancel()


def _unregister_user(user_id: str, dataset_id: str) -> bool:
    users = _dataset_users.get(dataset_id)
    if users:
        users.discard(user_id)
        if not users:
            del _dataset_users[dataset_id]
            return True
    return False


async def _release_after_delay(user_id: str, dataset_id: str, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    async with _lock:
        if _user_datasets.get(user_id) != dataset_id:
            return
        _user_timers.pop(user_id, None)
        _user_datasets.pop(user_id, None)
        should_unload = _unregister_user(user_id, dataset_id)
    if should_unload:
        from app.search.retriever import unload_dataset
        unload_dataset(dataset_id)
        print(f"[vram_manager] Released VRAM for dataset {dataset_id} (user {user_id} idle)")
