"""
Async-safe CRUD for datasets/registry.json.

Registry format: { "active": "<uuid>|null", "datasets": [...] }

Uses asyncio.Lock as fast in-process serializer; delegates file I/O to
registry_sync (which uses a cross-process file lock).
"""
import asyncio
from typing import Dict, List, Optional

from .registry_sync import (
    sync_read_registry, sync_write_registry,
    sync_get_active_id, sync_set_active_id,
    sync_list_datasets, sync_get_dataset, sync_update_dataset,
)

_REGISTRY_LOCK = asyncio.Lock()


async def load_registry() -> Dict:
    """Returns the full registry dict {active, datasets}."""
    async with _REGISTRY_LOCK:
        return sync_read_registry()


async def get_active_id() -> Optional[str]:
    async with _REGISTRY_LOCK:
        return sync_get_active_id()


async def set_active_id(dataset_id: Optional[str]) -> None:
    async with _REGISTRY_LOCK:
        sync_set_active_id(dataset_id)


async def list_datasets() -> List[Dict]:
    async with _REGISTRY_LOCK:
        return sync_list_datasets()


async def get_dataset(dataset_id: str) -> Optional[Dict]:
    async with _REGISTRY_LOCK:
        return sync_get_dataset(dataset_id)


async def create_dataset(entry: Dict) -> Dict:
    async with _REGISTRY_LOCK:
        data = sync_read_registry()
        data["datasets"].append(entry)
        sync_write_registry(data)
    return entry


async def update_dataset(dataset_id: str, patch: Dict) -> Optional[Dict]:
    async with _REGISTRY_LOCK:
        return sync_update_dataset(dataset_id, patch)


async def delete_dataset(dataset_id: str) -> bool:
    async with _REGISTRY_LOCK:
        data = sync_read_registry()
        original_len = len(data.get("datasets", []))
        data["datasets"] = [e for e in data["datasets"] if e["id"] != dataset_id]
        # Clear active pointer if the deleted dataset was active
        if data.get("active") == dataset_id:
            data["active"] = None
        sync_write_registry(data)
    return len(data["datasets"]) < original_len
