"""
Export / import RPC operations.

Export flow:
  client  →  dataset.export       →  spawn export_worker (job_type=export)
  client  →  dataset.export_status → check in-memory process registry + file existence

Import flow (archive with pre-built index):
  client  →  dataset.import        →  validate archive, create DB entry,
                                       spawn export_worker (job_type=import_with_index)
  client  →  dataset.get/build.status → standard progress polling

Import flow (FASTA-only archive):
  client  →  dataset.import        →  validate archive, extract FASTA in executor,
                                       create DB entry, spawn build_worker
  client  →  build.status / dataset.get → standard progress polling
"""
import asyncio
import json
import os
import subprocess
import sys
import uuid
from typing import Dict

from app.daemon.handler import register, HandlerError
from app.search.tasks import BLOCKING_EXECUTOR
from app.build.dataset_db import (
    blocking_create_dataset, blocking_get_dataset,
)
from app.core.config import DATASETS_ROOT as _DATASETS_ROOT_DEFAULT
from app.core import config_loader


def _get_datasets_root() -> str:
    return config_loader.get("storage", "datasets_root", "") or _DATASETS_ROOT_DEFAULT

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Daemon-owned export / import process registries
_ACTIVE_EXPORT_PROCESSES: Dict[str, dict] = {}   # dataset_id → {proc, output_path}
_ACTIVE_IMPORT_PROCESSES: Dict[str, subprocess.Popen] = {}  # dataset_id → proc


def _reap_finished() -> None:
    done_e = [did for did, info in _ACTIVE_EXPORT_PROCESSES.items()
              if info["proc"].poll() is not None]
    for did in done_e:
        del _ACTIVE_EXPORT_PROCESSES[did]

    done_i = [did for did, proc in _ACTIVE_IMPORT_PROCESSES.items()
              if proc.poll() is not None]
    for did in done_i:
        del _ACTIVE_IMPORT_PROCESSES[did]


def terminate_all_export_import_processes() -> None:
    """Called during daemon shutdown."""
    for proc_info in list(_ACTIVE_EXPORT_PROCESSES.values()):
        proc = proc_info["proc"]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    _ACTIVE_EXPORT_PROCESSES.clear()

    for proc in list(_ACTIVE_IMPORT_PROCESSES.values()):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    _ACTIVE_IMPORT_PROCESSES.clear()


def _check_access(entry: dict, user_id: str, role: str, require_owner: bool = False) -> None:
    """Raise HandlerError if the user may not access this dataset."""
    if role == "admin":
        return
    if require_owner and entry["owner_id"] != user_id:
        raise HandlerError(403, "Access denied")
    if entry["owner_id"] != user_id and entry.get("visibility") != "public":
        raise HandlerError(403, "Access denied")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@register("dataset.export")
async def dataset_export(params: dict, context: dict) -> dict:
    dataset_id = params.get("dataset_id")
    if not dataset_id:
        raise HandlerError(400, "dataset_id required")

    user_id = context["user_id"]
    role = context.get("role", "user")
    loop = asyncio.get_event_loop()

    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HandlerError(404, "Dataset not found")

    # Users can export their own or public datasets; admin can export any.
    _check_access(entry, user_id, role)

    if entry["status"] != "ready":
        raise HandlerError(400, "Dataset is not ready for export")

    _reap_finished()

    # Reject if already exporting
    existing = _ACTIVE_EXPORT_PROCESSES.get(dataset_id)
    if existing and existing["proc"].poll() is None:
        raise HandlerError(409, "Export already in progress for this dataset")

    output_path = os.path.join(DATASETS_ROOT, dataset_id, "export.7z")

    # Remove stale export if present
    if os.path.isfile(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    job_config = {
        "job_type": "export",
        "dataset_id": dataset_id,
        "output_path": output_path,
    }
    config_path = os.path.join(DATASETS_ROOT, dataset_id, "export_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(job_config, f)

    proc = subprocess.Popen(
        [sys.executable, "-m", "app.build.export_worker", "--config", config_path],
        cwd=_PROJECT_ROOT,
    )
    _ACTIVE_EXPORT_PROCESSES[dataset_id] = {"proc": proc, "output_path": output_path}

    return {"dataset_id": dataset_id, "status": "exporting"}


@register("dataset.export_status")
async def dataset_export_status(params: dict, context: dict) -> dict:
    dataset_id = params.get("dataset_id")
    if not dataset_id:
        raise HandlerError(400, "dataset_id required")

    user_id = context["user_id"]
    role = context.get("role", "user")
    loop = asyncio.get_event_loop()

    entry = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_get_dataset, dataset_id)
    if not entry:
        raise HandlerError(404, "Dataset not found")
    _check_access(entry, user_id, role)

    output_path = os.path.join(DATASETS_ROOT, dataset_id, "export.7z")
    proc_info = _ACTIVE_EXPORT_PROCESSES.get(dataset_id)

    if proc_info and proc_info["proc"].poll() is None:
        return {"dataset_id": dataset_id, "status": "exporting"}

    if os.path.isfile(output_path):
        return {
            "dataset_id": dataset_id,
            "status": "done",
            "export_path": output_path,
            "file_size": os.path.getsize(output_path),
            "dataset_name": entry.get("name", "export"),
        }

    if proc_info and proc_info["proc"].poll() not in (None, 0):
        return {"dataset_id": dataset_id, "status": "error"}

    return {"dataset_id": dataset_id, "status": "idle"}


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@register("dataset.import")
async def dataset_import(params: dict, context: dict) -> dict:
    archive_tmp_path = params.get("archive_tmp_path")
    if not archive_tmp_path or not os.path.isfile(archive_tmp_path):
        raise HandlerError(400, "archive_tmp_path missing or file not found")

    name = (params.get("name") or "").strip() or None
    user_id = context["user_id"]
    loop = asyncio.get_event_loop()

    # Validate archive (reads manifest, checks paths) — runs in executor
    from app.build.export_import import blocking_validate_archive
    try:
        manifest = await loop.run_in_executor(
            BLOCKING_EXECUTOR, blocking_validate_archive, archive_tmp_path
        )
    except ValueError as exc:
        raise HandlerError(400, f"Invalid archive: {exc}") from exc

    dataset_name = name or manifest["dataset"].get("name") or "imported"
    algorithm = manifest["dataset"].get("algorithm") or "flat"
    if algorithm not in ("flat", "ivfpq", "hnsw"):
        algorithm = "flat"

    _reap_finished()

    # Create dataset directory and DB entry
    dataset_id = str(uuid.uuid4())
    short_id = dataset_id[:8]
    dataset_dir = os.path.join(_get_datasets_root(), dataset_id)
    index_dir = os.path.join(dataset_dir, "indices")
    fasta_path = os.path.join(dataset_dir, "input.fasta")
    db_table = f"proteins_{short_id}"

    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(index_dir, exist_ok=True)

    entry = {
        "id": dataset_id,
        "owner_id": user_id,
        "name": dataset_name,
        "algorithm": algorithm,
        "status": "importing",
        "visibility": "private",
        "fasta_path": fasta_path,
        "db_table": db_table,
    }
    await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_create_dataset, entry)

    # Move archive into dataset dir so the worker can read it even after
    # the temp file might be cleaned up.
    import shutil
    archive_dest = os.path.join(dataset_dir, "import_archive.7z")
    shutil.move(archive_tmp_path, archive_dest)

    job_config = {
        "job_type": "import_with_index",
        "dataset_id": dataset_id,
        "archive_path": archive_dest,
        "dataset_dir": dataset_dir,
        "fasta_path": fasta_path,
        "db_table": db_table,
        "manifest": manifest,
    }
    config_path = os.path.join(dataset_dir, "import_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(job_config, f)

    proc = subprocess.Popen(
        [sys.executable, "-m", "app.build.export_worker", "--config", config_path],
        cwd=_PROJECT_ROOT,
    )
    _ACTIVE_IMPORT_PROCESSES[dataset_id] = proc

    return {"dataset_id": dataset_id, "status": "importing"}
