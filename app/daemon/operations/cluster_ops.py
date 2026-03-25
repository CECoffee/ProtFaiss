"""
Admin RPC handlers for cluster monitoring and management.

  cluster.list        — list all workers with metrics and admin_status
  cluster.set_status  — set a worker to available or unavailable
  cluster.set_hidden  — set a worker's hidden flag (visible only to admins)
"""
from app.daemon.handler import register
from app.scheduler.worker_registry import get_registry

_VALID_ADMIN_STATUSES = {"available", "unavailable", "hidden"}


@register("cluster.list")
async def cluster_list(params: dict, context: dict) -> dict:
    """Return a snapshot of all registered workers (metrics + admin_status)."""
    registry = get_registry()
    workers = await registry.snapshot()
    return {"workers": workers}


@register("cluster.set_status")
async def cluster_set_status(params: dict, context: dict) -> dict:
    """Set a worker's admin-managed availability.

    Params:
        node_id: str — the worker to update
        status: "available" | "unavailable"
    """
    node_id = params.get("node_id", "")
    status = params.get("status", "")

    if not node_id:
        return {"error": "node_id is required"}
    if status not in ("available", "unavailable"):
        return {"error": "status must be 'available' or 'unavailable'"}

    registry = get_registry()
    ok = await registry.set_admin_status(node_id, status)
    if not ok:
        return {"error": f"Worker '{node_id}' not found"}

    from app.scheduler.cluster_pool import get_cluster_pool
    pool = get_cluster_pool()
    if status == "unavailable":
        pool.disable_node(node_id)
    else:
        pool.enable_node(node_id)

    return {"ok": True, "node_id": node_id, "admin_status": status}


@register("cluster.set_hidden")
async def cluster_set_hidden(params: dict, context: dict) -> dict:
    """Set or clear the hidden flag on a worker.

    Params:
        node_id: str — the worker to update
        hidden: bool — True to hide, False to restore to available
    """
    node_id = params.get("node_id", "")
    hidden = params.get("hidden")

    if not node_id:
        return {"error": "node_id is required"}
    if hidden is None:
        return {"error": "hidden (bool) is required"}

    new_status = "hidden" if hidden else "available"
    registry = get_registry()
    ok = await registry.set_admin_status(node_id, new_status)
    if not ok:
        return {"error": f"Worker '{node_id}' not found"}

    from app.scheduler.cluster_pool import get_cluster_pool
    pool = get_cluster_pool()
    if hidden:
        pool.hide_node(node_id)
    else:
        pool.unhide_node(node_id)

    return {"ok": True, "node_id": node_id, "admin_status": new_status}
