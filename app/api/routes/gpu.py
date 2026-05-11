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


def _build_history_params(limit, offset, status_filter, task_type_filter,
                          task_id_filter, username_filter, start_date, end_date):
    params = {"limit": limit, "offset": offset}
    if status_filter:
        params["status_filter"] = status_filter.split(",")
    if task_type_filter:
        params["task_type_filter"] = task_type_filter
    if task_id_filter:
        params["task_id_filter"] = task_id_filter
    if username_filter:
        params["username_filter"] = username_filter
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return params


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


@router.post("/gpu/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, user: dict = Depends(get_current_user)):
    ctx = {"source": "api", "user_id": user["id"], "role": user["role"]}
    return await _call("gpu.cancel", {"task_id": task_id}, ctx)


@router.post("/admin/gpu/tasks/{task_id}/cancel")
async def admin_cancel_task(task_id: str, admin: dict = Depends(require_admin)):
    ctx = {"source": "api", "user_id": admin["id"], "role": "admin"}
    return await _call("gpu.cancel", {"task_id": task_id}, ctx)


@router.get("/gpu/history")
async def gpu_history(
    limit: int = 50,
    offset: int = 0,
    status_filter: str = None,
    task_type_filter: str = None,
    task_id_filter: str = None,
    username_filter: str = None,
    start_date: str = None,
    end_date: str = None,
    user: dict = Depends(get_current_user)
):
    ctx = {"source": "api", "user_id": user["id"], "role": user["role"]}
    params = _build_history_params(
        limit, offset, status_filter, task_type_filter,
        task_id_filter, username_filter, start_date, end_date,
    )
    return await _call("gpu.history", params, ctx)


@router.get("/admin/gpu/history")
async def admin_gpu_history(
    limit: int = 50,
    offset: int = 0,
    status_filter: str = None,
    task_type_filter: str = None,
    task_id_filter: str = None,
    username_filter: str = None,
    start_date: str = None,
    end_date: str = None,
    admin: dict = Depends(require_admin)
):
    ctx = {"source": "api", "user_id": admin["id"], "role": "admin"}
    params = _build_history_params(
        limit, offset, status_filter, task_type_filter,
        task_id_filter, username_filter, start_date, end_date,
    )
    return await _call("gpu.history", params, ctx)
