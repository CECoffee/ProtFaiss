"""
Async Redis client (singleton) for inter-process task state sharing.

Used by both the control plane (task dispatch) and worker nodes (result storage).
"""
import json
from typing import Optional

import redis.asyncio as aioredis

from app.core import config_loader

_client: Optional[aioredis.Redis] = None

TASK_TTL = 600  # seconds — task results expire after 10 minutes


def get_client() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("Redis client not initialized. Call init_client() first.")
    return _client


async def init_client() -> aioredis.Redis:
    global _client
    host = config_loader.get("redis", "host", "localhost")
    port = config_loader.get("redis", "port", 6379)
    db = config_loader.get("redis", "db", 0)
    password = config_loader.get("redis", "password", None) or None
    _client = aioredis.Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        decode_responses=True,
        max_connections=20,
    )
    await _client.ping()
    print(f"[redis] Connected to {host}:{port}/{db}")
    return _client


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------------------
# Task helpers
# ---------------------------------------------------------------------------

async def task_set(task_id: str, data: dict, ttl: int = TASK_TTL) -> None:
    await get_client().set(f"task:{task_id}", json.dumps(data, ensure_ascii=False), ex=ttl)


async def task_get(task_id: str) -> Optional[dict]:
    raw = await get_client().get(f"task:{task_id}")
    return json.loads(raw) if raw else None


async def task_delete(task_id: str) -> None:
    await get_client().delete(f"task:{task_id}")


async def task_update_fields(task_id: str, updates: dict, ttl: int = TASK_TTL) -> bool:
    """Atomic read-modify-write on a task entry. Returns False if task not found."""
    client = get_client()
    key = f"task:{task_id}"
    raw = await client.get(key)
    if raw is None:
        return False
    data = json.loads(raw)
    data.update(updates)
    await client.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
    return True
