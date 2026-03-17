"""
config_loader.py — 热重载 YAML 配置加载器

基于文件 mtime 自动感知变更：每次调用 get_config() 时检查文件修改时间，
文件变更则自动重新读取，无需重启服务。

也可调用 force_reload() 强制重载（用于 /admin/reload-config 端点）。
"""
import copy
import os
import threading
from typing import Any

import yaml

from app.core.config import CONFIG_YML_PATH

_lock = threading.Lock()
_cached_config: dict | None = None
_cached_mtime: float = -1.0

# 默认值（config.yml 缺失或解析失败时使用）
_DEFAULTS: dict = {
    "gpu": {
        "multi_gpu_enabled": True,
        "encoding_device": "auto",
        "faiss_devices": "auto",
        "faiss_temp_memory_mb": 1500,
        "memory_reserve_mb": 500,
        "fp16_lut": False,
    },
    "search": {
        "faiss_search_workers": 8,
        "max_concurrent_encodings": 3,
        "threadpool_workers": 32,
        "faiss_nprobe": 8,
        "time_release_vram": 300,
    },
    "build": {
        "encoding_batch_size": 32,
        "max_per_shard": 500000,
        "db_batch_size": 500,
        "ivfpq_nlist": 256,
        "ivfpq_m": 64,
        "ivfpq_nbits": 8,
        "hnsw_m": 32,
        "hnsw_ef_construction": 200,
        "add_batch_size": 200000,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """将 override 深度合并到 base 的副本中，返回新 dict。"""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _load_from_file() -> dict:
    """从磁盘读取并解析 config.yml，与默认值合并后返回。"""
    try:
        with open(CONFIG_YML_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return _deep_merge(_DEFAULTS, data)
    except FileNotFoundError:
        print(f"[config_loader] WARNING: {CONFIG_YML_PATH} not found, using defaults.")
        return copy.deepcopy(_DEFAULTS)
    except yaml.YAMLError as e:
        print(f"[config_loader] WARNING: YAML parse error in {CONFIG_YML_PATH}: {e}, using defaults.")
        return copy.deepcopy(_DEFAULTS)


def get_config() -> dict:
    """
    返回当前配置的深拷贝。
    若 config.yml 自上次读取后被修改，自动重新加载。
    """
    global _cached_config, _cached_mtime
    try:
        current_mtime = os.path.getmtime(CONFIG_YML_PATH)
    except OSError:
        current_mtime = -1.0

    with _lock:
        if _cached_config is None or current_mtime != _cached_mtime:
            _cached_config = _load_from_file()
            _cached_mtime = current_mtime

        return copy.deepcopy(_cached_config)


def force_reload() -> dict:
    """强制重新读取 config.yml，忽略 mtime 缓存。返回新配置。"""
    global _cached_config, _cached_mtime
    with _lock:
        _cached_config = _load_from_file()
        try:
            _cached_mtime = os.path.getmtime(CONFIG_YML_PATH)
        except OSError:
            _cached_mtime = -1.0
        return copy.deepcopy(_cached_config)


def get(section: str, key: str, default: Any = None) -> Any:
    """便捷访问：get("search", "faiss_search_workers") → 8"""
    cfg = get_config()
    return cfg.get(section, {}).get(key, default)
