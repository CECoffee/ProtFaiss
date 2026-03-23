"""
Config and system health operations.
"""
from app.daemon.handler import register
from app.core import config_loader
from app.search.retriever import _CACHE, _CACHE_LOCK


def _pool_snapshot() -> dict:
    if config_loader.get("cluster", "enabled", False):
        from app.scheduler.cluster_pool import get_cluster_pool
        return get_cluster_pool().snapshot()
    from app.scheduler.gpu_pool import get_pool
    return get_pool().snapshot()


@register("config.get")
async def config_get(params: dict, context: dict) -> dict:
    return config_loader.get_config()


@register("config.reload")
async def config_reload(params: dict, context: dict) -> dict:
    new_cfg = config_loader.force_reload()
    if not config_loader.get("cluster", "enabled", False):
        from app.scheduler.gpu_pool import get_pool
        total_slots = config_loader.get("scheduler", "total_gpu_slots", 1)
        get_pool().total_slots = total_slots
    return {"status": "reloaded", "config": new_cfg}


@register("system.health")
async def system_health(params: dict, context: dict) -> dict:
    return {
        "status": "ok",
        "shards": len(_CACHE),
        "gpu_pool": _pool_snapshot(),
    }
