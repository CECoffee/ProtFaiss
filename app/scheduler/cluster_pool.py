"""
Cluster-aware GPU pool — tracks slot allocation across multiple worker nodes.

Replaces single-node GpuPool when cluster.enabled = true.
Each worker node registers its total slot count on startup (via worker.register).
"""
import threading
from typing import Dict, Optional, Tuple


class ClusterGpuPool:
    """
    Thread-safe GPU slot pool for a multi-node cluster.

    Internals:
        _node_slots:   node_id → total slots on that node
        _allocations:  task_id → (node_id, n_slots)
    """

    def __init__(self):
        self._node_slots: Dict[str, int] = {}
        self._allocations: Dict[str, Tuple[str, int]] = {}
        self._lock = threading.Lock()

    def register_node(self, node_id: str, total_slots: int) -> None:
        with self._lock:
            self._node_slots[node_id] = total_slots

    def remove_node(self, node_id: str) -> None:
        with self._lock:
            self._node_slots.pop(node_id, None)
            freed = [tid for tid, (nid, _) in self._allocations.items() if nid == node_id]
            for tid in freed:
                del self._allocations[tid]

    def available_on_node(self, node_id: str) -> int:
        with self._lock:
            total = self._node_slots.get(node_id, 0)
            used = sum(s for nid, s in self._allocations.values() if nid == node_id)
            return max(0, total - used)

    @property
    def total_slots(self) -> int:
        with self._lock:
            return sum(self._node_slots.values())

    @property
    def available_slots(self) -> int:
        with self._lock:
            total = sum(self._node_slots.values())
            used = sum(s for _, s in self._allocations.values())
            return max(0, total - used)

    def allocate(self, task_id: str, n_slots: int, node_id: Optional[str] = None) -> Optional[str]:
        """
        Try to allocate n_slots on node_id (or any node if None).
        Returns the node_id on success, None if no capacity available.
        """
        with self._lock:
            candidates = [node_id] if node_id else list(self._node_slots.keys())
            for nid in candidates:
                total = self._node_slots.get(nid, 0)
                used = sum(s for n, s in self._allocations.values() if n == nid)
                if used + n_slots <= total:
                    self._allocations[task_id] = (nid, n_slots)
                    return nid
            return None

    def release(self, task_id: str) -> None:
        with self._lock:
            self._allocations.pop(task_id, None)

    def snapshot(self) -> dict:
        with self._lock:
            node_used: Dict[str, int] = {}
            for _, (nid, s) in self._allocations.items():
                node_used[nid] = node_used.get(nid, 0) + s
            return {
                "nodes": {
                    nid: {
                        "total": total,
                        "used": node_used.get(nid, 0),
                        "available": max(0, total - node_used.get(nid, 0)),
                    }
                    for nid, total in self._node_slots.items()
                },
                "total_slots": sum(self._node_slots.values()),
                "used_slots": sum(s for _, s in self._allocations.values()),
            }


# Module-level singleton
_pool: Optional[ClusterGpuPool] = None


def get_cluster_pool() -> ClusterGpuPool:
    if _pool is None:
        raise RuntimeError("Cluster pool not initialized. Call init_cluster_pool() first.")
    return _pool


def init_cluster_pool() -> ClusterGpuPool:
    global _pool
    _pool = ClusterGpuPool()
    return _pool
