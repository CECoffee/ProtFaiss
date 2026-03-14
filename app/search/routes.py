import asyncio

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from .tasks import submit_task, get_task, remove_task, BLOCKING_EXECUTOR
from app.build.dataset_db import blocking_get_user_active_id, blocking_get_dataset
from app.auth.dependencies import get_current_user

router = APIRouter()


class SearchRequest(BaseModel):
    sequence: str
    top_k: int = 5
    pooling: str = "mean"


class SubmitResponse(BaseModel):
    task_id: str


@router.post("/query/submit", response_model=SubmitResponse)
async def submit(req: SearchRequest, current_user: dict = Depends(get_current_user)):
    if not req.sequence:
        raise HTTPException(status_code=400, detail="sequence required")

    loop = asyncio.get_event_loop()
    active_id = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_get_user_active_id, current_user["id"]
    )
    if active_id is None:
        raise HTTPException(
            status_code=409,
            detail="No dataset is active. Please activate a dataset before searching.",
        )

    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, active_id)
    if entry is None or entry.get("status") != "ready":
        raise HTTPException(
            status_code=409,
            detail="Active dataset is not ready. Please activate a ready dataset.",
        )

    task_id = await submit_task(
        req.sequence, req.top_k, req.pooling, entry["db_table"],
        user_id=current_user["id"],
        dataset_id=active_id,
        index_dir=entry["index_dir"],
    )
    return {"task_id": task_id}


@router.get("/query/result/{task_id}")
async def get_result(task_id: str, current_user: dict = Depends(get_current_user)):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    # Only the task owner or admin can see the result
    if task.get("user_id") != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    if task["status"] == "done":
        remove_task(task_id)
    return task
