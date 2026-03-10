import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.search.routes import router as api_router
from app.build.routes import router as build_router, terminate_build_processes
from app.core.encoder import init_model
from app.search.retriever import load_shards, FAISS_SHARDS
from app.core.db import init_db_pool, close_db_pool
from app.core.config import ESM2_MODEL_DIR, CORS_ORIGINS, DATASETS_ROOT
from app.build.dataset_registry import load_registry, update_dataset, get_active_id, get_dataset, set_active_id

app = FastAPI(title="Protein Search")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(build_router)


@app.on_event("startup")
async def startup():
    print("startup: init model, init db pool ...")
    init_model(ESM2_MODEL_DIR)
    init_db_pool()

    os.makedirs(DATASETS_ROOT, exist_ok=True)

    # Load active dataset's shards if an active dataset exists
    active_id = await get_active_id()
    if active_id:
        entry = await get_dataset(active_id)
        if entry and entry.get("status") == "ready":
            try:
                load_shards(entry["index_dir"])
                print(f"startup: loaded {len(FAISS_SHARDS)} shards for dataset {active_id}")
            except Exception as e:
                print(f"startup: failed to load shards for active dataset {active_id}: {e}")
        else:
            print(f"startup: active dataset {active_id} is not ready — no shards loaded")
    else:
        print("startup: no active dataset — search disabled until a dataset is activated")

    # Mark stale 'building' entries as 'error' (server restarted mid-build)
    try:
        registry = await load_registry()
        for entry in registry.get("datasets", []):
            if entry.get("status") == "building":
                await update_dataset(entry["id"], {
                    "status": "error",
                    "error_msg": "Server restarted during build",
                    "progress_step": "error",
                })
                print(f"startup: marked stale build {entry['id']} as error")
    except Exception as e:
        print(f"startup: registry cleanup error: {e}")

    print("startup done: shards:", len(FAISS_SHARDS))


@app.on_event("shutdown")
def shutdown():
    print("shutdown: terminating build subprocesses ...")
    terminate_build_processes()
    print("shutdown: closing db pool ...")
    close_db_pool()


@app.get("/health")
def health():
    from app.build.registry_sync import sync_get_active_id
    return {
        "status": "ok",
        "shards": len(FAISS_SHARDS),
        "active_dataset_id": sync_get_active_id(),
    }


# uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
