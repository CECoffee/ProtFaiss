"""GPU routes — thin wrapper over daemon IPC."""
from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user, require_admin
from app.api.ipc_client import get_client, IpcError

router = APIRouter(tags=["gpu"])


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router.get("/gpu/queue")
async def gpu_queue(user: dict = Depends(get_current_user)):
    ctx = {"source": "api", "user_id": user["id"], "role": user["role"]}
    return await _call("gpu.queue", {}, ctx)


@router.get("/gpu/status")
async def gpu_status(user: dict = Depends(get_current_user)):
    ctx = {"source": "api", "user_id": user["id"], "role": user["role"]}
    return await _call("gpu.status", {}, ctx)


@router.get("/admin/gpu/queue")
async def admin_gpu_queue(admin: dict = Depends(require_admin)):
    ctx = {"source": "api", "user_id": admin["id"], "role": "admin"}
    return await _call("gpu.admin_queue", {}, ctx)


@router.post("/admin/gpu/tasks/{task_id}/cancel")
async def admin_cancel_task(task_id: str, admin: dict = Depends(require_admin)):
    ctx = {"source": "api", "user_id": admin["id"], "role": "admin"}
    return await _call("gpu.cancel", {"task_id": task_id}, ctx)
