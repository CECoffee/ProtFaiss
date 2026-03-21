"""
API service entry point.

Startup: connect IPC client to daemon, health-check.
Shutdown: close IPC connections.
"""
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import CORS_ORIGINS
from app.api.ipc_client import init_client, close_client, get_client, IpcError
from app.api.routes import auth, search, build, datasets, users, gpu, health, export_import

app = FastAPI(title="ProtFaiss API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(search.router)
app.include_router(build.router)
app.include_router(datasets.router)
app.include_router(users.router)
app.include_router(gpu.router)
app.include_router(health.router)
app.include_router(export_import.router)


@app.on_event("startup")
async def startup():
    # Small pool for JWT validation (get_current_user → blocking_get_user_by_id)
    from app.core.db import init_db_pool
    init_db_pool()

    await init_client()
    try:
        await get_client().call("system.health", {}, {"source": "api", "role": "system"})
        print("[api] Daemon health check passed")
    except Exception as e:
        print(f"[api] WARNING: Daemon health check failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    from app.core.db import close_db_pool
    close_db_pool()
    await close_client()
