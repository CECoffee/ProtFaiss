"""
API routes for dataset building and management.

Endpoints:
  POST   /build/submit          — multipart: file + name + algorithm + params
  GET    /build/status/{id}     — returns dataset registry entry
  GET    /datasets              — returns {datasets: [...], active_dataset_id: str|null}
  DELETE /datasets/{id}         — deletes registry entry + files + DB table
  POST   /datasets/switch       — {dataset_id} → reload shards, update active
"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from .config import IVFPQ_NLIST, IVFPQ_M, IVFPQ_NBITS, HNSW_M, HNSW_EF_CONSTRUCTION
from .dataset_registry import (
    create_dataset, get_dataset, update_dataset, delete_dataset, list_datasets,
    get_active_id, set_active_id,
)
from .db_operations import blocking_drop_table
from app.search.retriever import swap_active_dataset
from app.search.tasks import BLOCKING_EXECUTOR
from app.core.config import DATASETS_ROOT

router = APIRouter()

# Project root: directory containing the `app` package
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Active build subprocesses keyed by dataset_id
_ACTIVE_BUILD_PROCESSES: Dict[str, subprocess.Popen] = {}


class SwitchRequest(BaseModel):
    dataset_id: str


def _reap_finished_processes() -> None:
    """Remove finished subprocesses from the tracking dict."""
    done = [did for did, proc in _ACTIVE_BUILD_PROCESSES.items() if proc.poll() is not None]
    for did in done:
        del _ACTIVE_BUILD_PROCESSES[did]


def terminate_build_processes() -> None:
    """Terminate all active build subprocesses. Called on server shutdown."""
    for dataset_id, proc in list(_ACTIVE_BUILD_PROCESSES.items()):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    _ACTIVE_BUILD_PROCESSES.clear()


# ---------------------------------------------------------------------------
# POST /build/submit
# ---------------------------------------------------------------------------

@router.post("/build/submit")
async def build_submit(
    file: UploadFile = File(...),
    name: str = Form(...),
    algorithm: str = Form("flat"),
    nlist: int = Form(IVFPQ_NLIST),
    pq_m: int = Form(IVFPQ_M),
    nbits: int = Form(IVFPQ_NBITS),
    hnsw_m: int = Form(HNSW_M),
    ef_construction: int = Form(HNSW_EF_CONSTRUCTION),
):
    if algorithm not in ("flat", "ivfpq", "hnsw"):
        raise HTTPException(status_code=400, detail="algorithm must be flat, ivfpq, or hnsw")

    _reap_finished_processes()

    dataset_id = str(uuid.uuid4())
    short_id = dataset_id[:8]
    dataset_dir = os.path.join(DATASETS_ROOT, dataset_id)
    index_dir = os.path.join(dataset_dir, "indices")
    fasta_path = os.path.join(dataset_dir, "input.fasta")
    db_table = f"proteins_{short_id}"

    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(index_dir, exist_ok=True)

    # Save uploaded FASTA
    content = await file.read()
    with open(fasta_path, "wb") as f:
        f.write(content)

    entry = {
        "id": dataset_id,
        "name": name,
        "created_at": time.time(),
        "algorithm": algorithm,
        "status": "building",
        "error_msg": None,
        "fasta_path": fasta_path,
        "index_dir": index_dir,
        "db_table": db_table,
        "num_sequences": 0,
        "num_indexed": 0,
        "progress_step": "idle",
        "progress_pct": 0,
    }
    await create_dataset(entry)

    # Write build config for the worker subprocess
    config = {
        "dataset_id": dataset_id,
        "fasta_path": fasta_path,
        "db_table": db_table,
        "index_dir": index_dir,
        "algorithm": algorithm,
        "nlist": nlist,
        "pq_m": pq_m,
        "nbits": nbits,
        "hnsw_m": hnsw_m,
        "ef_construction": ef_construction,
    }
    config_path = os.path.join(dataset_dir, "build_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f)

    proc = subprocess.Popen(
        [sys.executable, "-m", "app.build.worker", "--config", config_path],
        cwd=_PROJECT_ROOT,
    )
    _ACTIVE_BUILD_PROCESSES[dataset_id] = proc

    return {"dataset_id": dataset_id, "status": "building"}


# ---------------------------------------------------------------------------
# GET /build/status/{id}
# ---------------------------------------------------------------------------

@router.get("/build/status/{dataset_id}")
async def build_status(dataset_id: str):
    entry = await get_dataset(dataset_id)
    if not entry:
        raise HTTPException(status_code=404, detail="dataset not found")
    return entry


# ---------------------------------------------------------------------------
# GET /datasets
# ---------------------------------------------------------------------------

@router.get("/datasets")
async def datasets_list():
    entries = await list_datasets()
    active_id = await get_active_id()
    return {
        "datasets": entries,
        "active_dataset_id": active_id,
    }


# ---------------------------------------------------------------------------
# DELETE /datasets/{id}
# ---------------------------------------------------------------------------

@router.delete("/datasets/{dataset_id}")
async def datasets_delete(dataset_id: str):
    entry = await get_dataset(dataset_id)
    if not entry:
        raise HTTPException(status_code=404, detail="dataset not found")

    # Terminate build subprocess if still running
    proc = _ACTIVE_BUILD_PROCESSES.pop(dataset_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Delete dataset files
    dataset_dir = os.path.join(DATASETS_ROOT, dataset_id)
    if os.path.isdir(dataset_dir):
        shutil.rmtree(dataset_dir, ignore_errors=True)

    # Drop DB table
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_drop_table, entry["db_table"])

    await delete_dataset(dataset_id)
    return {"deleted": dataset_id}


# ---------------------------------------------------------------------------
# POST /datasets/switch
# ---------------------------------------------------------------------------

@router.post("/datasets/switch")
async def datasets_switch(req: SwitchRequest):
    entry = await get_dataset(req.dataset_id)
    if not entry:
        raise HTTPException(status_code=404, detail="dataset not found")
    if entry["status"] != "ready":
        raise HTTPException(status_code=400, detail="dataset is not ready")

    import asyncio
    loop = asyncio.get_event_loop()
    n_shards = await loop.run_in_executor(
        BLOCKING_EXECUTOR, swap_active_dataset, entry["index_dir"]
    )
    await set_active_id(req.dataset_id)
    return {"active_dataset_id": req.dataset_id, "shards_loaded": n_shards}
