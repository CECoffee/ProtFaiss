"""
search/config.py — 搜索模块运行时配置

所有值从 config.yml 热重载读取。
FAISS_SHARD_DIR 由数据集切换逻辑在运行时设置，不在此处管理。
"""
from app.core.config_loader import get

# 保留模块级常量作为初始默认值（兼容直接 import 的旧代码）
FAISS_SHARD_DIR = "indices/1m"


def get_faiss_search_workers() -> int:
    return get("search", "faiss_search_workers", 8)


def get_max_concurrent_encodings() -> int:
    return get("search", "max_concurrent_encodings", 3)


def get_threadpool_workers() -> int:
    return get("search", "threadpool_workers", 32)


def get_faiss_nprobe() -> int:
    return get("search", "faiss_nprobe", 8)


# 向后兼容：保留旧常量名（读取当前配置值）
FAISS_SEARCH_WORKERS: int = get_faiss_search_workers()
MAX_CONCURRENT_ENCODINGS: int = get_max_concurrent_encodings()
THREADPOOL_WORKERS: int = get_threadpool_workers()
