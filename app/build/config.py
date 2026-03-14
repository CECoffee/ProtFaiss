"""
build/config.py — 构建模块运行时配置

所有值从 config.yml 热重载读取。
"""
from app.core.config_loader import get


def get_ivfpq_nlist() -> int:
    return get("build", "ivfpq_nlist", 256)


def get_ivfpq_m() -> int:
    return get("build", "ivfpq_m", 64)


def get_ivfpq_nbits() -> int:
    return get("build", "ivfpq_nbits", 8)


def get_hnsw_m() -> int:
    return get("build", "hnsw_m", 32)


def get_hnsw_ef_construction() -> int:
    return get("build", "hnsw_ef_construction", 200)


def get_encoding_batch_size() -> int:
    return get("build", "encoding_batch_size", 32)


def get_max_per_shard() -> int:
    return get("build", "max_per_shard", 500000)


def get_db_batch_size() -> int:
    return get("build", "db_batch_size", 500)


def get_add_batch_size() -> int:
    return get("build", "add_batch_size", 200000)


# 向后兼容：保留旧常量名
HNSW_M: int = get_hnsw_m()
HNSW_EF_CONSTRUCTION: int = get_hnsw_ef_construction()
IVFPQ_NLIST: int = get_ivfpq_nlist()
IVFPQ_M: int = get_ivfpq_m()
IVFPQ_NBITS: int = get_ivfpq_nbits()
