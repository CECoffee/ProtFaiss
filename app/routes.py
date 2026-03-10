from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from .tasks import submit_task, get_task, remove_task

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
    task_id = await submit_task(req.sequence, req.top_k, req.pooling)
    return {"task_id": task_id}

@router.get("/query/result/{task_id}")
async def get_result(task_id: str):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] == "done":
        remove_task(task_id)
    return task

