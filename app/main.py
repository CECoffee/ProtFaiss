import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.search.routes import router as api_router
from app.build.routes import router as build_router, terminate_build_processes
from app.auth.routes import router as auth_router
from app.users.routes import router as users_router
from app.scheduler.routes import router as scheduler_router
from app.core.encoder import init_model
from app.search.retriever import load_shards, FAISS_SHARDS
from app.core.db import init_db_pool, close_db_pool
from app.core.config import ESM2_MODEL_DIR, CORS_ORIGINS, DATASETS_ROOT
from app.core import config_loader
from app.core import gpu as _gpu

app = FastAPI(title="FaaIndex — Protein Search")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(api_router)
app.include_router(build_router)
app.include_router(users_router)
app.include_router(scheduler_router)


@app.on_event("startup")
async def startup():
    print("startup: init model, init db pool ...")
    _gpu.log_gpu_status()
    init_model(ESM2_MODEL_DIR)
    init_db_pool()

    # Run DB migration and ensure admin user exists
    from app.auth.init_admin import ensure_admin
    ensure_admin()

    os.makedirs(DATASETS_ROOT, exist_ok=True)

    # Initialize GPU pool from config
    from app.scheduler.gpu_pool import init_pool
    total_slots = config_loader.get("scheduler", "total_gpu_slots", 4)
    init_pool(total_slots)
    print(f"startup: GPU pool initialized with {total_slots} slots")

    # Start GPU scheduler
    from app.scheduler.scheduler import init_scheduler
    scheduler = init_scheduler()
    scheduler.start()

    # Mark stale 'building' datasets as error
    try:
        from app.build.dataset_db import blocking_list_all_datasets, blocking_update_dataset
        all_datasets = blocking_list_all_datasets()
        for entry in all_datasets:
            if entry.get("status") == "building":
                blocking_update_dataset(entry["id"], {
                    "status": "error",
                    "error_msg": "Server restarted during build",
                    "progress_step": "error",
                })
                print(f"startup: marked stale build {entry['id']} as error")
    except Exception as e:
        print(f"startup: dataset cleanup error: {e}")

    print("startup done")


@app.on_event("shutdown")
async def shutdown():
    print("shutdown: cancelling VRAM timers ...")
    from app.search import vram_timer
    await vram_timer.cancel_all()
    print("shutdown: stopping GPU scheduler ...")
    from app.scheduler.scheduler import get_scheduler
    sched = get_scheduler()
    if sched:
        sched.stop()
    print("shutdown: closing db pool ...")
    close_db_pool()


@app.get("/health")
def health():
    from app.scheduler.gpu_pool import get_pool as get_gpu_pool
    return {
        "status": "ok",
        "shards": len(FAISS_SHARDS),
        "gpu_pool": get_gpu_pool().snapshot(),
    }


@app.get("/gpu/status")
def gpu_status():
    from app.scheduler.gpu_pool import get_pool as get_gpu_pool
    return {
        "gpus": _gpu.get_all_gpu_status(),
        "available_devices": _gpu.get_available_devices(),
        "encoding_device": str(_gpu.get_encoding_device()),
        "multi_gpu_enabled": config_loader.get("gpu", "multi_gpu_enabled", True),
        "pool": get_gpu_pool().snapshot(),
    }


@app.post("/admin/reload-config")
def reload_config():
    """强制重载 config.yml，立即生效。"""
    new_cfg = config_loader.force_reload()
    # Update GPU pool size if changed
    from app.scheduler.gpu_pool import get_pool as get_gpu_pool
    total_slots = config_loader.get("scheduler", "total_gpu_slots", 4)
    get_gpu_pool().total_slots = total_slots
    return {"status": "reloaded", "config": new_cfg}


# uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
