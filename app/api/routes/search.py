"""Search routes — thin wrapper over daemon IPC."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.api.ipc_client import get_client, IpcError

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    sequence: str
    top_k: int = 5
    pooling: str = "mean"


def _ctx(user: dict) -> dict:
    return {"source": "api", "user_id": user["id"], "role": user["role"]}


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router.post("/query/submit")
async def submit(req: SearchRequest, user: dict = Depends(get_current_user)):
    return await _call("search.submit", req.model_dump(), _ctx(user))


@router.get("/query/result/{task_id}")
async def get_result(task_id: str, user: dict = Depends(get_current_user)):
    return await _call("search.result", {"task_id": task_id}, _ctx(user))


@router.get("/query/history")
async def get_history(
    limit: int = 20,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    return await _call("search.history_list", {"limit": limit, "offset": offset}, _ctx(user))


@router.get("/query/history/{task_id}")
async def get_history_detail(task_id: str, user: dict = Depends(get_current_user)):
    return await _call("search.history_detail", {"search_task_id": task_id}, _ctx(user))
