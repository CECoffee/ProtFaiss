"""
gpu.py — GPU 设备管理模块

提供：
- 设备枚举与显存查询
- 多 GPU 开关感知（读取 config.yml gpu.multi_gpu_enabled）
- FAISS StandardGpuResources 工厂（每线程每 GPU 独立实例）
- 编码设备选择
"""
from __future__ import annotations

from typing import Union

import torch


def get_device_count() -> int:
    """返回可用 CUDA 设备数量，无 GPU 时返回 0。"""
    return torch.cuda.device_count() if torch.cuda.is_available() else 0


def get_gpu_memory(device_id: int) -> dict:
    """
    返回指定 GPU 的显存信息（MB）。
    {"total": int, "used": int, "free": int}
    """
    if not torch.cuda.is_available() or device_id >= get_device_count():
        return {"total": 0, "used": 0, "free": 0}
    free_bytes, total_bytes = torch.cuda.mem_get_info(device_id)
    used_bytes = total_bytes - free_bytes
    return {
        "total": total_bytes // (1024 * 1024),
        "used": used_bytes // (1024 * 1024),
        "free": free_bytes // (1024 * 1024),
    }


def get_all_gpu_status() -> list[dict]:
    """返回所有 GPU 的显存状态列表。"""
    return [
        {"id": i, **get_gpu_memory(i)}
        for i in range(get_device_count())
    ]


def get_available_devices() -> list[int]:
    """
    根据 config.yml 的 gpu.multi_gpu_enabled 和 gpu.faiss_devices 返回可用设备列表。

    - multi_gpu_enabled=false → [0]（单卡模式，无 GPU 时 []）
    - multi_gpu_enabled=true, faiss_devices="auto" → 所有可用 GPU
    - multi_gpu_enabled=true, faiss_devices=[0,1] → 指定列表（过滤掉不存在的）
    """
    from app.core.config_loader import get_config
    cfg = get_config()
    gpu_cfg = cfg.get("gpu", {})

    n = get_device_count()
    if n == 0:
        return []

    if not gpu_cfg.get("multi_gpu_enabled", True):
        return [0]

    faiss_devices = gpu_cfg.get("faiss_devices", "auto")
    if faiss_devices == "auto":
        return list(range(n))

    if isinstance(faiss_devices, list):
        return [d for d in faiss_devices if isinstance(d, int) and 0 <= d < n]

    return list(range(n))


def get_encoding_device() -> torch.device:
    """
    返回 ESM2 编码使用的 torch.device。

    - "auto" → 选显存最多的 GPU；无 GPU 时返回 cpu
    - "cuda:N" → 指定 GPU
    - "cpu" → 强制 CPU
    """
    from app.core.config_loader import get_config
    cfg = get_config()
    setting = cfg.get("gpu", {}).get("encoding_device", "auto")
    reserve_mb = cfg.get("gpu", {}).get("memory_reserve_mb", 500)

    if setting == "cpu":
        return torch.device("cpu")

    if not torch.cuda.is_available():
        return torch.device("cpu")

    n = get_device_count()
    if n == 0:
        return torch.device("cpu")

    if setting == "auto":
        # 选显存最多的 GPU（超过 reserve_mb 阈值）
        best_id, best_free = 0, -1
        for i in range(n):
            mem = get_gpu_memory(i)
            if mem["free"] > best_free:
                best_free, best_id = mem["free"], i
        if best_free < reserve_mb:
            print(f"[gpu] WARNING: all GPUs have < {reserve_mb} MB free, falling back to CPU for encoding.")
            return torch.device("cpu")
        return torch.device(f"cuda:{best_id}")

    # 显式指定，如 "cuda:0"
    try:
        return torch.device(setting)
    except RuntimeError:
        print(f"[gpu] WARNING: invalid encoding_device '{setting}', falling back to CPU.")
        return torch.device("cpu")


def get_fp16_lut() -> bool:
    """返回是否启用 FP16 LUT（IVF-PQ GPU 检索优化）。"""
    from app.core.config_loader import get
    return bool(get("gpu", "fp16_lut", False))


def create_gpu_cloner_options():
    """
    创建 faiss.GpuClonerOptions，根据配置设置 useFloat16LookupTables。
    传入 faiss.index_cpu_to_gpu 的第四个参数。
    """
    import faiss
    co = faiss.GpuClonerOptions()
    co.useFloat16 = get_fp16_lut()
    return co


def create_faiss_gpu_resources(device_id: int):
    """
    为指定 GPU 创建一个 faiss.StandardGpuResources 实例。
    每个线程、每个 GPU 必须使用独立实例（FAISS 要求）。
    设置 tempMemory 以限制临时显存占用。
    """
    import faiss
    from app.core.config_loader import get
    temp_mb = get("gpu", "faiss_temp_memory_mb", 1500)
    res = faiss.StandardGpuResources()
    res.setTempMemory(temp_mb * 1024 * 1024)
    return res


def log_gpu_status() -> None:
    """打印所有 GPU 的显存状态（启动时诊断用）。"""
    n = get_device_count()
    if n == 0:
        print("[gpu] No CUDA GPUs available.")
        return
    for info in get_all_gpu_status():
        print(
            f"[gpu] GPU {info['id']}: "
            f"total={info['total']}MB  used={info['used']}MB  free={info['free']}MB"
        )
    devices = get_available_devices()
    print(f"[gpu] Available devices for FAISS: {devices}")
    enc_dev = get_encoding_device()
    print(f"[gpu] Encoding device: {enc_dev}")
