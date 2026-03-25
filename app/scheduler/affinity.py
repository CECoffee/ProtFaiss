"""
Dataset affinity routing — selects the best worker node for a task.

For search tasks:
  1. Prefer workers that already have the target dataset in VRAM (cache hit → no cold load).
  2. Fall back to the worker with the most free GPU slots.

For build tasks:
  Any worker with available slots and 'build' capability.

Admin-status filtering:
  - Workers with admin_status == 'unavailable' are excluded from all scheduling.
  - Workers with admin_status == 'hidden' are excluded unless is_admin=True.
"""
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.scheduler.worker_registry import WorkerInfo
    from app.scheduler.cluster_pool import ClusterGpuPool


def select_worker_for_search(
    workers: "List[WorkerInfo]",
    pool: "ClusterGpuPool",
    dataset_id: Optional[str],
    n_slots: int = 1,
    is_admin: bool = False,
) -> "Optional[WorkerInfo]":
    """
    Select the best worker for a search task.

    Priority:
      1. Worker with dataset in VRAM cache AND available slots (cache-affinity)
      2. Worker with the most free GPU slots (least loaded)

    Returns None if no worker has capacity.
    """
    eligible = [
        w for w in workers
        if "search" in w.capabilities
        and pool.available_on_node(w.node_id) >= n_slots
        and w.admin_status != "unavailable"
        and (is_admin or w.admin_status != "hidden")
    ]
    if not eligible:
        return None

    if dataset_id:
        cached = [w for w in eligible if dataset_id in w.cached_datasets]
        if cached:
            return max(cached, key=lambda w: pool.available_on_node(w.node_id))

    return max(eligible, key=lambda w: pool.available_on_node(w.node_id))


def select_worker_for_build(
    workers: "List[WorkerInfo]",
    pool: "ClusterGpuPool",
    n_slots: int = 1,
    is_admin: bool = False,
) -> "Optional[WorkerInfo]":
    """Select the least-loaded capable worker for a build task."""
    eligible = [
        w for w in workers
        if "build" in w.capabilities
        and pool.available_on_node(w.node_id) >= n_slots
        and w.admin_status != "unavailable"
        and (is_admin or w.admin_status != "hidden")
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda w: pool.available_on_node(w.node_id))
