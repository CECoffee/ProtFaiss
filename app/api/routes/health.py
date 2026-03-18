"""Health routes."""
from fastapi import APIRouter, HTTPException

from app.api.ipc_client import get_client, IpcError

router = APIRouter(tags=["health"])


async def _call(method, params, context):
    try:
        return await get_client().call(method, params, context)
    except IpcError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router.get("/health")
async def health():
    return await _call("system.health", {}, {"source": "api", "role": "system"})
