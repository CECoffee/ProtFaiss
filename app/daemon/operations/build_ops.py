"""
Build operations: submit a build job and query its status.

In legacy mode (cluster.enabled=false):
  Spawns a local subprocess (app.build.worker) directly.

In cluster mode (cluster.enabled=true):
  Writes build_config.json to shared storage (NFS), then enqueues a
  gpu_task. The cluster scheduler dispatches it to a remote worker node.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from typing import Dict

from app.daemon.handler import register, HandlerError
from app.search.tasks import BLOCKING_EXECUTOR
from app.build.dataset_db import blocking_create_dataset, blocking_get_dataset
from app.build.config import (
    get_ivfpq_nlist, get_ivfpq_m, get_ivfpq_nbits,
    get_hnsw_m, get_hnsw_ef_construction,
)
from app.core.config import DATASETS_ROOT
from app.core import config_loader

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

_ACTIVE_BUILD_PROCESSES: Dict[str, subprocess.Popen] = {}


def _cluster_enabled() -> bool:
    return config_loader.get("cluster", "enabled", False)


def _reap_finished_processes() -> None:
    done = [did for did, proc in _ACTIVE_BUILD_PROCESSES.items() if proc.poll() is not None]
    for did in done:
        del _ACTIVE_BUILD_PROCESSES[did]


def terminate_all_build_processes() -> None:
    for dataset_id, proc in list(_ACTIVE_BUILD_PROCESSES.items()):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    _ACTIVE_BUILD_PROCESSES.clear()


@register("build.submit")
async def build_submit(params: dict, context: dict) -> dict:
    algorithm = params.get("algorithm", "flat")
    if algorithm not in ("flat", "ivfpq", "hnsw"):
        raise HandlerError(400, "algorithm must be flat, ivfpq, or hnsw")

    user_id = context["user_id"]
    name = params.get("name", "untitled")

    fasta_tmp_path = params.get("fasta_tmp_path")
    if not fasta_tmp_path or not os.path.isfile(fasta_tmp_path):
        raise HandlerError(400, "fasta_tmp_path missing or file not found")

    nlist = params.get("nlist") or get_ivfpq_nlist()
    pq_m = params.get("pq_m") or get_ivfpq_m()
    nbits = params.get("nbits") or get_ivfpq_nbits()
    hnsw_m = params.get("hnsw_m") or get_hnsw_m()
    ef_construction = params.get("ef_construction") or get_hnsw_ef_construction()

    if not _cluster_enabled():
        _reap_finished_processes()

    dataset_id = str(uuid.uuid4())
    short_id = dataset_id[:8]
    dataset_dir = os.path.join(DATASETS_ROOT, dataset_id)
    index_dir = os.path.join(dataset_dir, "indices")
    fasta_path = os.path.join(dataset_dir, "input.fasta")
    db_table = f"proteins_{short_id}"

    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(index_dir, exist_ok=True)
    shutil.move(fasta_tmp_path, fasta_path)

    entry = {
        "id": dataset_id,
        "owner_id": user_id,
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

    build_config = {
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
        "multi_gpu_enabled": config_loader.get("gpu", "multi_gpu_enabled", True),
        "fp16_lut": config_loader.get("gpu", "fp16_lut", False),
    }
    config_path = os.path.join(dataset_dir, "build_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(build_config, f)

    if _cluster_enabled():
        # Cluster mode: enqueue gpu_task; scheduler dispatches to a remote worker
        from app.scheduler.scheduler import blocking_enqueue_build
        await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_enqueue_build, dataset_id, user_id)
    else:
        # Legacy mode: spawn local subprocess
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.build.worker", "--config", config_path],
            cwd=_PROJECT_ROOT,
        )
        _ACTIVE_BUILD_PROCESSES[dataset_id] = proc

    return {"dataset_id": dataset_id, "status": "building"}


@register("build.status")
async def build_status(params: dict, context: dict) -> dict:
    dataset_id = params.get("dataset_id")
    if not dataset_id:
        raise HandlerError(400, "dataset_id required")

    user_id = context["user_id"]
    role = context.get("role", "user")
    loop = asyncio.get_event_loop()

    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HandlerError(404, "dataset not found")
    if entry["owner_id"] != user_id and entry["visibility"] != "public" and role != "admin":
        raise HandlerError(403, "Access denied")
    return entry
