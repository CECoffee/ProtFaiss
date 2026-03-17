"""
API routes for dataset building and management.

Endpoints:
  POST   /build/submit              — multipart: file + name + algorithm + params
  GET    /build/status/{id}         — returns dataset entry
  GET    /datasets                  — returns {datasets: [...], active_dataset_id: str|null}
  DELETE /datasets/{id}             — deletes dataset entry + files + DB table
  POST   /datasets/switch           — {dataset_id} → reload shards, update active
  PATCH  /datasets/{id}/visibility  — {visibility: "public"|"private"}
"""
import json
import os
import shutil
import subprocess
import sys
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel

from .config import get_ivfpq_nlist, get_ivfpq_m, get_ivfpq_nbits, get_hnsw_m, get_hnsw_ef_construction
from .dataset_db import (
    blocking_create_dataset, blocking_get_dataset, blocking_update_dataset,
    blocking_delete_dataset, blocking_list_datasets_for_user,
    blocking_get_user_active_id, blocking_set_user_active_dataset,
    blocking_clear_user_active_dataset,
)
from .db_operations import blocking_drop_table
from app.search.tasks import BLOCKING_EXECUTOR
from app.search import vram_timer
from app.core.config import DATASETS_ROOT
from app.auth.dependencies import get_current_user, require_admin

import asyncio

router = APIRouter()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Active build subprocesses keyed by dataset_id
_ACTIVE_BUILD_PROCESSES: Dict[str, subprocess.Popen] = {}


class SwitchRequest(BaseModel):
    dataset_id: str


class VisibilityRequest(BaseModel):
    visibility: str


def _reap_finished_processes() -> None:
    done = [did for did, proc in _ACTIVE_BUILD_PROCESSES.items() if proc.poll() is not None]
    for did in done:
        del _ACTIVE_BUILD_PROCESSES[did]


def terminate_build_processes() -> None:
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
    nlist: int = Form(None),
    pq_m: int = Form(None),
    nbits: int = Form(None),
    hnsw_m: int = Form(None),
    ef_construction: int = Form(None),
    current_user: dict = Depends(get_current_user),
):
    if algorithm not in ("flat", "ivfpq", "hnsw"):
        raise HTTPException(status_code=400, detail="algorithm must be flat, ivfpq, or hnsw")

    nlist = nlist if nlist is not None else get_ivfpq_nlist()
    pq_m = pq_m if pq_m is not None else get_ivfpq_m()
    nbits = nbits if nbits is not None else get_ivfpq_nbits()
    hnsw_m = hnsw_m if hnsw_m is not None else get_hnsw_m()
    ef_construction = ef_construction if ef_construction is not None else get_hnsw_ef_construction()

    _reap_finished_processes()

    dataset_id = str(uuid.uuid4())
    short_id = dataset_id[:8]
    dataset_dir = os.path.join(DATASETS_ROOT, dataset_id)
    index_dir = os.path.join(dataset_dir, "indices")
    fasta_path = os.path.join(dataset_dir, "input.fasta")
    db_table = f"proteins_{short_id}"

    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(index_dir, exist_ok=True)

    content = await file.read()
    with open(fasta_path, "wb") as f:
        f.write(content)

    entry = {
        "id": dataset_id,
        "owner_id": current_user["id"],
        "name": name,
        "algorithm": algorithm,
        "status": "building",
        "visibility": "private",
        "fasta_path": fasta_path,
        "index_dir": index_dir,
        "db_table": db_table,
    }
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_create_dataset, entry)

    from app.core.config_loader import get as cfg_get
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
        "multi_gpu_enabled": cfg_get("gpu", "multi_gpu_enabled", True),
        "fp16_lut": cfg_get("gpu", "fp16_lut", False),
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
async def build_status(dataset_id: str, current_user: dict = Depends(get_current_user)):
    loop = asyncio.get_event_loop()
    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HTTPException(status_code=404, detail="dataset not found")
    # Allow access if owner or public
    if entry["owner_id"] != current_user["id"] and entry["visibility"] != "public" and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    return entry


# ---------------------------------------------------------------------------
# GET /datasets
# ---------------------------------------------------------------------------

@router.get("/datasets")
async def datasets_list(current_user: dict = Depends(get_current_user)):
    loop = asyncio.get_event_loop()
    entries = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_list_datasets_for_user, current_user["id"]
    )
    active_id = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_get_user_active_id, current_user["id"]
    )
    return {"datasets": entries, "active_dataset_id": active_id}


# ---------------------------------------------------------------------------
# DELETE /datasets/{id}
# ---------------------------------------------------------------------------

@router.delete("/datasets/{dataset_id}")
async def datasets_delete(dataset_id: str, current_user: dict = Depends(get_current_user)):
    loop = asyncio.get_event_loop()
    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HTTPException(status_code=404, detail="dataset not found")
    if entry["owner_id"] != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    proc = _ACTIVE_BUILD_PROCESSES.pop(dataset_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    dataset_dir = os.path.join(DATASETS_ROOT, dataset_id)
    if os.path.isdir(dataset_dir):
        shutil.rmtree(dataset_dir, ignore_errors=True)

    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_drop_table, entry["db_table"])
    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_delete_dataset, dataset_id)
    return {"deleted": dataset_id}


# ---------------------------------------------------------------------------
# POST /datasets/switch
# ---------------------------------------------------------------------------

@router.post("/datasets/switch")
async def datasets_switch(req: SwitchRequest, current_user: dict = Depends(get_current_user)):
    loop = asyncio.get_event_loop()
    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, req.dataset_id)
    if not entry:
        raise HTTPException(status_code=404, detail="dataset not found")
    if entry["status"] != "ready":
        raise HTTPException(status_code=400, detail="dataset is not ready")
    # Must be owner or public
    if entry["owner_id"] != current_user["id"] and entry["visibility"] != "public" and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    # Cancel idle timer and immediately release old dataset's VRAM for this user
    await vram_timer.cancel_and_release(current_user["id"])

    await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_set_user_active_dataset, current_user["id"], req.dataset_id
    )
    return {"active_dataset_id": req.dataset_id}


# ---------------------------------------------------------------------------
# PATCH /datasets/{id}/visibility
# ---------------------------------------------------------------------------

@router.patch("/datasets/{dataset_id}/visibility")
async def datasets_set_visibility(
    dataset_id: str,
    req: VisibilityRequest,
    current_user: dict = Depends(get_current_user),
):
    if req.visibility not in ("public", "private"):
        raise HTTPException(status_code=400, detail="visibility must be 'public' or 'private'")

    loop = asyncio.get_event_loop()
    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HTTPException(status_code=404, detail="dataset not found")
    if entry["owner_id"] != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    updated = await loop.run_in_executor(
        BLOCKING_EXECUTOR, blocking_update_dataset, dataset_id, {"visibility": req.visibility}
    )
    return updated
