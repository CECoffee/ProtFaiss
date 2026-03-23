"""Cluster management routes — admin only."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.api.ipc_client import get_client, IpcError

router = APIRouter(tags=["cluster"])


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


class WorkerStatusBody(BaseModel):
    status: str  # "available" | "unavailable"


class WorkerHiddenBody(BaseModel):
    hidden: bool


@router.get("/admin/cluster/workers")
async def list_workers(admin: dict = Depends(require_admin)):
    ctx = {"source": "api", "user_id": admin["id"], "role": "admin"}
    return await _call("cluster.list", {}, ctx)


@router.post("/admin/cluster/workers/{node_id}/status")
async def set_worker_status(
    node_id: str,
    body: WorkerStatusBody,
    admin: dict = Depends(require_admin),
):
    ctx = {"source": "api", "user_id": admin["id"], "role": "admin"}
    return await _call("cluster.set_status", {"node_id": node_id, "status": body.status}, ctx)


@router.post("/admin/cluster/workers/{node_id}/hidden")
async def set_worker_hidden(
    node_id: str,
    body: WorkerHiddenBody,
    admin: dict = Depends(require_admin),
):
    ctx = {"source": "api", "user_id": admin["id"], "role": "admin"}
    return await _call("cluster.set_hidden", {"node_id": node_id, "hidden": body.hidden}, ctx)
