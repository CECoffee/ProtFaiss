"""
GPU resource pool — tracks slot allocation in memory.
"""
import threading
from typing import Dict, List, Set


class GpuPool:
    def __init__(self, total_slots: int):
        self._total = total_slots
        # task_id → number of slots held
        self._allocated: Dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def total_slots(self) -> int:
        return self._total

    @total_slots.setter
    def total_slots(self, value: int):
        with self._lock:
            self._total = max(0, value)

    @property
    def available_slots(self) -> int:
        with self._lock:
            used = sum(self._allocated.values())
            return max(0, self._total - used)

    @property
    def used_slots(self) -> int:
        with self._lock:
            return sum(self._allocated.values())

    def allocate(self, task_id: str, n_slots: int) -> bool:
        """Try to allocate n_slots for task_id. Returns True on success."""
        with self._lock:
            used = sum(self._allocated.values())
            if used + n_slots > self._total:
                return False
            self._allocated[task_id] = n_slots
            return True

    def release(self, task_id: str) -> None:
        with self._lock:
            self._allocated.pop(task_id, None)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_slots": self._total,
                "used_slots": sum(self._allocated.values()),
                "available_slots": max(0, self._total - sum(self._allocated.values())),
                "allocations": dict(self._allocated),
            }


# Module-level singleton — initialized in main.py startup
_pool: GpuPool = GpuPool(total_slots=4)


def get_pool() -> GpuPool:
    return _pool


def init_pool(total_slots: int) -> GpuPool:
    global _pool
    _pool = GpuPool(total_slots=total_slots)
    return _pool
