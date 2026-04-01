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
        _node_slots:    node_id → total slots on that node
        _disabled:      unavailable nodes (excluded from all slot counts and allocation)
        _hidden:        hidden nodes (excluded from user-facing counts; admins can still allocate)
        _allocations:   task_id → (node_id, n_slots)
    """

    def __init__(self):
        self._node_slots: Dict[str, int] = {}
        self._disabled: set = set()
        self._hidden: set = set()
        self._allocations: Dict[str, Tuple[str, int]] = {}
        self._lock = threading.Lock()

    def register_node(self, node_id: str, total_slots: int) -> None:
        with self._lock:
            self._node_slots[node_id] = total_slots

    def remove_node(self, node_id: str) -> None:
        with self._lock:
            self._node_slots.pop(node_id, None)
            self._disabled.discard(node_id)
            self._hidden.discard(node_id)
            freed = [tid for tid, (nid, _) in self._allocations.items() if nid == node_id]
            for tid in freed:
                del self._allocations[tid]

    def disable_node(self, node_id: str) -> None:
        """Exclude unavailable node from all slot counts and allocation."""
        with self._lock:
            self._disabled.add(node_id)
            self._hidden.discard(node_id)  # unavailable supersedes hidden

    def enable_node(self, node_id: str) -> None:
        """Restore node to fully available."""
        with self._lock:
            self._disabled.discard(node_id)
            self._hidden.discard(node_id)

    def hide_node(self, node_id: str) -> None:
        """Mark node as hidden: excluded from user-facing counts; admins can allocate."""
        with self._lock:
            if node_id not in self._disabled:
                self._hidden.add(node_id)

    def unhide_node(self, node_id: str) -> None:
        """Remove hidden flag from node."""
        with self._lock:
            self._hidden.discard(node_id)

    def available_on_node(self, node_id: str) -> int:
        with self._lock:
            if node_id in self._disabled:
                return 0
            total = self._node_slots.get(node_id, 0)
            used = sum(s for nid, s in self._allocations.values() if nid == node_id)
            return max(0, total - used)

    @property
    def total_slots(self) -> int:
        """Total slots visible to admins (excludes unavailable, includes hidden)."""
        with self._lock:
            return sum(v for k, v in self._node_slots.items() if k not in self._disabled)

    @property
    def total_slots_user(self) -> int:
        """Total slots visible to regular users (excludes unavailable and hidden)."""
        with self._lock:
            excluded = self._disabled | self._hidden
            return sum(v for k, v in self._node_slots.items() if k not in excluded)

    @property
    def available_slots(self) -> int:
        """Available slots for admins."""
        with self._lock:
            total = sum(v for k, v in self._node_slots.items() if k not in self._disabled)
            used = sum(s for nid, s in self._allocations.values() if nid not in self._disabled)
            return max(0, total - used)

    @property
    def available_slots_user(self) -> int:
        """Available slots for regular users."""
        with self._lock:
            excluded = self._disabled | self._hidden
            total = sum(v for k, v in self._node_slots.items() if k not in excluded)
            used = sum(s for nid, s in self._allocations.values() if nid not in excluded)
            return max(0, total - used)

    def allocate(self, task_id: str, n_slots: int, node_id: Optional[str] = None) -> Optional[str]:
        """
        Try to allocate n_slots on node_id (or any node if None).
        Returns the node_id on success, None if no capacity available.
        """
        with self._lock:
            candidates = [node_id] if node_id else list(self._node_slots.keys())
            for nid in candidates:
                if nid in self._disabled:
                    continue
                total = self._node_slots.get(nid, 0)
                used = sum(s for n, s in self._allocations.values() if n == nid)
                if used + n_slots <= total:
                    self._allocations[task_id] = (nid, n_slots)
                    return nid
            return None

    def release(self, task_id: str) -> None:
        with self._lock:
            self._allocations.pop(task_id, None)

    def snapshot(self, is_admin: bool = True) -> dict:
        with self._lock:
            excluded = self._disabled if is_admin else (self._disabled | self._hidden)
            node_used: Dict[str, int] = {}
            for _, (nid, s) in self._allocations.items():
                node_used[nid] = node_used.get(nid, 0) + s
            total = sum(v for k, v in self._node_slots.items() if k not in excluded)
            used = sum(s for nid, s in self._allocations.values() if nid not in excluded)
            return {
                "nodes": {
                    nid: {
                        "total": total,
                        "used": node_used.get(nid, 0),
                        "available": max(0, total - node_used.get(nid, 0)),
                        "disabled": nid in self._disabled,
                        "hidden": nid in self._hidden,
                    }
                    for nid, total in self._node_slots.items()
                    if nid not in excluded
                },
                "total_slots": total,
                "used_slots": used,
                "available_slots": max(0, total - used),
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
