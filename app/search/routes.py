from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .tasks import submit_task, get_task, remove_task
from app.build.dataset_registry import get_active_id, get_dataset

router = APIRouter()


class SearchRequest(BaseModel):
    sequence: str
    top_k: int = 5
    pooling: str = "mean"


class SubmitResponse(BaseModel):
    task_id: str


@router.post("/query/submit", response_model=SubmitResponse)
async def submit(req: SearchRequest):
    if not req.sequence:
        raise HTTPException(status_code=400, detail="sequence required")

    active_id = await get_active_id()
    if active_id is None:
        raise HTTPException(
            status_code=409,
            detail="No dataset is active. Please import and activate a dataset before searching.",
        )

    entry = await get_dataset(active_id)
    if entry is None or entry.get("status") != "ready":
        raise HTTPException(
            status_code=409,
            detail="Active dataset is not ready. Please activate a ready dataset.",
        )

    task_id = await submit_task(req.sequence, req.top_k, req.pooling, entry["db_table"])
    return {"task_id": task_id}


@router.get("/query/result/{task_id}")
async def get_result(task_id: str):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] == "done":
        remove_task(task_id)
    return task
