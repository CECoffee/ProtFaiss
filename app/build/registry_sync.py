"""
Synchronous (non-async) registry file I/O with cross-process file locking.

Used by:
  - app/build/dataset_registry.py  (main async process, via asyncio.Lock wrapper)
  - app/build/worker.py             (subprocess, directly)

Registry format:
  {
    "active": "<uuid>" | null,
    "datasets": [ { ...entry... }, ... ]
  }

Old array format is auto-migrated on first read.
All writes are atomic: temp file → os.replace().
"""
import json
import os
import tempfile
from typing import Dict, List, Optional

from app.core.config import REGISTRY_PATH, DATASETS_ROOT

_LOCK_PATH = REGISTRY_PATH + ".lock"
_LOCK_TIMEOUT = 10  # seconds

try:
    from filelock import FileLock, Timeout as _FLTimeout
    _HAS_FILELOCK = True
except ImportError:
    _HAS_FILELOCK = False

    class FileLock:  # type: ignore[no-redef]
        """No-op fallback when filelock is not installed."""
        def __init__(self, path, timeout=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    class _FLTimeout(Exception):  # type: ignore[no-redef]
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dir() -> None:
    os.makedirs(DATASETS_ROOT, exist_ok=True)


def _read_raw() -> Dict:
    """Read registry JSON; migrates old array format. NOT file-locked."""
    _ensure_dir()
    if not os.path.exists(REGISTRY_PATH):
        return {"active": None, "datasets": []}
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Migrate old array format
    if isinstance(data, list):
        data = {"active": None, "datasets": data}
    return data


def _write_raw(data: Dict) -> None:
    """Atomic write: write to temp file then os.replace(). NOT file-locked."""
    _ensure_dir()
    dir_ = os.path.dirname(os.path.abspath(REGISTRY_PATH))
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, REGISTRY_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_read_registry() -> Dict:
    """Read registry under file lock. Returns {active, datasets}."""
    try:
        with FileLock(_LOCK_PATH, timeout=_LOCK_TIMEOUT):
            return _read_raw()
    except _FLTimeout:
        raise RuntimeError("Registry file lock timed out")


def sync_write_registry(data: Dict) -> None:
    """Write registry under file lock."""
    try:
        with FileLock(_LOCK_PATH, timeout=_LOCK_TIMEOUT):
            _write_raw(data)
    except _FLTimeout:
        raise RuntimeError("Registry file lock timed out")


def sync_get_active_id() -> Optional[str]:
    return sync_read_registry().get("active")


def sync_set_active_id(dataset_id: Optional[str]) -> None:
    try:
        with FileLock(_LOCK_PATH, timeout=_LOCK_TIMEOUT):
            data = _read_raw()
            data["active"] = dataset_id
            _write_raw(data)
    except _FLTimeout:
        raise RuntimeError("Registry file lock timed out")


def sync_list_datasets() -> List[Dict]:
    return sync_read_registry().get("datasets", [])


def sync_get_dataset(dataset_id: str) -> Optional[Dict]:
    for entry in sync_list_datasets():
        if entry["id"] == dataset_id:
            return entry
    return None


def sync_update_dataset(dataset_id: str, patch: Dict) -> Optional[Dict]:
    """Update a single dataset entry under file lock. Returns updated entry or None."""
    try:
        with FileLock(_LOCK_PATH, timeout=_LOCK_TIMEOUT):
            data = _read_raw()
            updated = None
            for i, entry in enumerate(data.get("datasets", [])):
                if entry["id"] == dataset_id:
                    data["datasets"][i] = {**entry, **patch}
                    updated = data["datasets"][i]
                    break
            _write_raw(data)
        return updated
    except _FLTimeout:
        raise RuntimeError("Registry file lock timed out")
