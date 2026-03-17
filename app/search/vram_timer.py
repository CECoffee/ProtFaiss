"""
vram_timer.py — Per-user idle VRAM release timer.

After a search completes, reset_timer() starts a countdown for that user.
If the user searches again before expiry, the timer resets.
If the user switches dataset, cancel_and_release() immediately unloads the old dataset.
Each user has an independent timer.
"""
import asyncio
from typing import Dict, Optional

from app.core import config_loader

# user_id -> running asyncio.Task
_user_timers: Dict[str, asyncio.Task] = {}
# user_id -> dataset_id they last searched
_user_datasets: Dict[str, str] = {}
# dataset_id -> set of user_ids with active timers referencing it
_dataset_users: Dict[str, set] = {}

_lock = asyncio.Lock()


async def reset_timer(user_id: str, dataset_id: str) -> None:
    """
    Called after a search completes. Starts (or resets) the idle timer for this user.
    If time_release_vram <= 0, the feature is disabled and nothing happens.
    """
    delay = config_loader.get("search", "time_release_vram", 300)
    if not delay or delay <= 0:
        return

    async with _lock:
        # Cancel existing timer for this user
        _cancel_timer_nolock(user_id)

        # If user switched dataset since last timer, unregister from old dataset
        old_dataset = _user_datasets.get(user_id)
        if old_dataset and old_dataset != dataset_id:
            _unregister_user_nolock(user_id, old_dataset)

        # Register user for this dataset
        _dataset_users.setdefault(dataset_id, set()).add(user_id)
        _user_datasets[user_id] = dataset_id

        task = asyncio.create_task(_release_after_delay(user_id, dataset_id, delay))
        _user_timers[user_id] = task


async def cancel_and_release(user_id: str) -> None:
    """
    Called when user switches dataset. Immediately cancels the timer and
    unloads the old dataset from VRAM if no other users reference it.
    """
    async with _lock:
        _cancel_timer_nolock(user_id)
        old_dataset = _user_datasets.pop(user_id, None)
        if old_dataset:
            should_unload = _unregister_user_nolock(user_id, old_dataset)
            if should_unload:
                # Import here to avoid circular imports at module load time
                from app.search.retriever import unload_dataset
                unload_dataset(old_dataset)


async def cancel_all() -> None:
    """Called on server shutdown. Cancels all pending timers."""
    async with _lock:
        for task in list(_user_timers.values()):
            task.cancel()
        _user_timers.clear()
        _user_datasets.clear()
        _dataset_users.clear()


# ---------------------------------------------------------------------------
# Internal helpers (must be called with _lock held)
# ---------------------------------------------------------------------------

def _cancel_timer_nolock(user_id: str) -> None:
    task = _user_timers.pop(user_id, None)
    if task and not task.done():
        task.cancel()


def _unregister_user_nolock(user_id: str, dataset_id: str) -> bool:
    """Remove user from dataset's refcount. Returns True if refcount hit zero."""
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
        # Only proceed if this user's current dataset is still the same
        if _user_datasets.get(user_id) != dataset_id:
            return
        _user_timers.pop(user_id, None)
        _user_datasets.pop(user_id, None)
        should_unload = _unregister_user_nolock(user_id, dataset_id)

    if should_unload:
        from app.search.retriever import unload_dataset
        unload_dataset(dataset_id)
        print(f"[vram_timer] Released VRAM for dataset {dataset_id} (user {user_id} idle)")
