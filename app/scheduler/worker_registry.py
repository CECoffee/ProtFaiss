"""
Worker registry — tracks registered GPU worker nodes and their liveness.

Workers connect to the control plane IPC port and call worker.register.
The control plane then creates a reverse WorkerClient connection to each
worker for task dispatch.

Heartbeats update the last_seen timestamp; stale workers are marked dead
by check_liveness(), which is called each scheduler tick.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

from app.core import config_loader

if TYPE_CHECKING:
    from app.daemon.worker_client import WorkerClient


@dataclass
class WorkerInfo:
    node_id: str
    address: str               # "host:port" — control plane connects here
    gpu_count: int
    gpu_slots: int             # total schedulable GPU slots on this node
    capabilities: List[str]    # ["encode", "search", "build"]
    cached_datasets: List[str] = field(default_factory=list)
    running_tasks: int = 0
    status: str = "online"     # online | draining | dead
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    client: Optional["WorkerClient"] = None


class WorkerRegistry:
    def __init__(self):
        self._workers: Dict[str, WorkerInfo] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        node_id: str,
        address: str,
        gpu_count: int,
        gpu_slots: int,
        capabilities: List[str],
    ) -> None:
        async with self._lock:
            if node_id in self._workers:
                w = self._workers[node_id]
                w.address = address
                w.gpu_count = gpu_count
                w.gpu_slots = gpu_slots
                w.capabilities = capabilities
                w.status = "online"
                w.last_seen = time.time()
                print(f"[registry] Worker re-registered: {node_id} @ {address}")
            else:
                self._workers[node_id] = WorkerInfo(
                    node_id=node_id,
                    address=address,
                    gpu_count=gpu_count,
                    gpu_slots=gpu_slots,
                    capabilities=capabilities,
                )
                print(f"[registry] Worker registered: {node_id} @ {address} ({gpu_slots} slots)")

    async def heartbeat(
        self,
        node_id: str,
        cached_datasets: List[str],
        running_tasks: int,
    ) -> None:
        async with self._lock:
            w = self._workers.get(node_id)
            if w:
                w.last_seen = time.time()
                w.cached_datasets = cached_datasets
                w.running_tasks = running_tasks
                w.status = "online"

    async def set_client(self, node_id: str, client: "WorkerClient") -> None:
        async with self._lock:
            w = self._workers.get(node_id)
            if w:
                w.client = client

    async def get_online_workers(self) -> List[WorkerInfo]:
        timeout = config_loader.get("cluster", "heartbeat_timeout", 15)
        now = time.time()
        async with self._lock:
            return [
                w for w in self._workers.values()
                if w.status == "online" and (now - w.last_seen) < timeout
            ]

    async def get_worker(self, node_id: str) -> Optional[WorkerInfo]:
        async with self._lock:
            return self._workers.get(node_id)

    async def deregister(self, node_id: str) -> None:
        """Gracefully remove a worker that has announced shutdown."""
        async with self._lock:
            w = self._workers.pop(node_id, None)
            if w is None:
                return
            if w.client:
                asyncio.create_task(w.client.close())
        # Release GPU slots from ClusterGpuPool
        from app.scheduler.cluster_pool import get_cluster_pool
        get_cluster_pool().remove_node(node_id)
        print(f"[registry] Worker deregistered: {node_id}")

    async def check_liveness(self) -> None:
        """Mark stale workers as dead. Called each scheduler tick."""
        timeout = config_loader.get("cluster", "heartbeat_timeout", 15)
        now = time.time()
        async with self._lock:
            for w in list(self._workers.values()):
                if w.status == "online" and (now - w.last_seen) > timeout:
                    w.status = "dead"
                    if w.client:
                        asyncio.create_task(w.client.close())
                        w.client = None
                    print(f"[registry] Worker timed out: {w.node_id}")

    async def snapshot(self) -> List[dict]:
        async with self._lock:
            return [
                {
                    "node_id": w.node_id,
                    "address": w.address,
                    "gpu_count": w.gpu_count,
                    "gpu_slots": w.gpu_slots,
                    "capabilities": w.capabilities,
                    "cached_datasets": w.cached_datasets,
                    "running_tasks": w.running_tasks,
                    "status": w.status,
                    "last_seen": w.last_seen,
                }
                for w in self._workers.values()
            ]


# Module-level singleton — initialized in daemon __main__
_registry: Optional[WorkerRegistry] = None


def get_registry() -> WorkerRegistry:
    if _registry is None:
        raise RuntimeError("Worker registry not initialized. Call init_registry() first.")
    return _registry


def init_registry() -> WorkerRegistry:
    global _registry
    _registry = WorkerRegistry()
    return _registry
