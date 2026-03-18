"""Dataset routes — thin wrapper over daemon IPC."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.api.ipc_client import get_client, IpcError

router = APIRouter(tags=["datasets"])


class SwitchRequest(BaseModel):
    dataset_id: str


class VisibilityRequest(BaseModel):
    visibility: str


def _ctx(user: dict) -> dict:
    return {"source": "api", "user_id": user["id"], "role": user["role"]}


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router.get("/datasets")
async def datasets_list(user: dict = Depends(get_current_user)):
    return await _call("dataset.list", {}, _ctx(user))


@router.get("/datasets/{dataset_id}")
async def dataset_get(dataset_id: str, user: dict = Depends(get_current_user)):
    return await _call("dataset.get", {"dataset_id": dataset_id}, _ctx(user))


@router.delete("/datasets/{dataset_id}")
async def datasets_delete(dataset_id: str, user: dict = Depends(get_current_user)):
    return await _call("dataset.delete", {"dataset_id": dataset_id}, _ctx(user))


@router.post("/datasets/switch")
async def datasets_switch(req: SwitchRequest, user: dict = Depends(get_current_user)):
    return await _call("dataset.switch", {"dataset_id": req.dataset_id}, _ctx(user))


@router.patch("/datasets/{dataset_id}/visibility")
async def datasets_visibility(
    dataset_id: str,
    req: VisibilityRequest,
    user: dict = Depends(get_current_user),
):
    return await _call(
        "dataset.visibility",
        {"dataset_id": dataset_id, "visibility": req.visibility},
        _ctx(user),
    )
