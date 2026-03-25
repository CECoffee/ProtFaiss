"""
Worker system metrics collector.

Collects CPU, memory, and GPU metrics for inclusion in heartbeat payloads.
All collection is non-blocking; missing libraries or GPU errors return sentinel
values (-1 / empty list) rather than raising.
"""
from __future__ import annotations

from typing import Any

try:
    import psutil as _psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False

try:
    import warnings as _warnings
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        import pynvml as _pynvml
    _pynvml.nvmlInit()
    _PYNVML_AVAILABLE = True
except Exception:
    _pynvml = None  # type: ignore
    _PYNVML_AVAILABLE = False


def collect_metrics() -> dict[str, Any]:
    """Return a snapshot of current system metrics.

    Returns:
        {
            "cpu_percent": float | -1,
            "memory_total_mb": int | -1,
            "memory_used_mb": int | -1,
            "memory_percent": float | -1,
            "gpus": [
                {
                    "id": int,
                    "name": str,
                    "utilization_percent": float | -1,
                    "vram_total_mb": int | -1,
                    "vram_used_mb": int | -1,
                    "vram_percent": float | -1,
                    "temperature_c": int | -1,
                },
                ...
            ]
        }
    """
    return {
        "cpu_percent": _cpu_percent(),
        **_memory_info(),
        "gpus": _gpu_info(),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cpu_percent() -> float:
    if not _PSUTIL_AVAILABLE:
        return -1.0
    try:
        return float(_psutil.cpu_percent(interval=None))
    except Exception:
        return -1.0


def _memory_info() -> dict[str, Any]:
    if not _PSUTIL_AVAILABLE:
        return {"memory_total_mb": -1, "memory_used_mb": -1, "memory_percent": -1.0}
    try:
        vm = _psutil.virtual_memory()
        return {
            "memory_total_mb": vm.total // (1024 * 1024),
            "memory_used_mb": vm.used // (1024 * 1024),
            "memory_percent": float(vm.percent),
        }
    except Exception:
        return {"memory_total_mb": -1, "memory_used_mb": -1, "memory_percent": -1.0}


def _gpu_info() -> list[dict[str, Any]]:
    if _PYNVML_AVAILABLE:
        return _gpu_info_pynvml()
    return _gpu_info_nvidiasmi()


def _gpu_info_pynvml() -> list[dict[str, Any]]:
    try:
        count = _pynvml.nvmlDeviceGetCount()
    except Exception:
        return []

    result = []
    for i in range(count):
        entry: dict[str, Any] = {"id": i, "name": "unknown",
                                  "utilization_percent": -1.0,
                                  "vram_total_mb": -1, "vram_used_mb": -1,
                                  "vram_percent": -1.0, "temperature_c": -1}
        try:
            handle = _pynvml.nvmlDeviceGetHandleByIndex(i)
            entry["name"] = _pynvml.nvmlDeviceGetName(handle)
            util = _pynvml.nvmlDeviceGetUtilizationRates(handle)
            entry["utilization_percent"] = float(util.gpu)
            mem = _pynvml.nvmlDeviceGetMemoryInfo(handle)
            entry["vram_total_mb"] = mem.total // (1024 * 1024)
            entry["vram_used_mb"] = mem.used // (1024 * 1024)
            if mem.total > 0:
                entry["vram_percent"] = round(mem.used / mem.total * 100, 1)
            entry["temperature_c"] = int(
                _pynvml.nvmlDeviceGetTemperature(handle, _pynvml.NVML_TEMPERATURE_GPU)
            )
        except Exception:
            pass
        result.append(entry)
    return result


def _gpu_info_nvidiasmi() -> list[dict[str, Any]]:
    """Parse nvidia-smi CSV output as fallback when pynvml is unavailable."""
    import subprocess
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return []
    except Exception:
        return []

    result = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            idx = int(parts[0])
            name = parts[1]
            util = float(parts[2])
            vram_used = int(parts[3])
            vram_total = int(parts[4])
            temp = int(parts[5])
            vram_pct = round(vram_used / vram_total * 100, 1) if vram_total > 0 else -1.0
            result.append({
                "id": idx,
                "name": name,
                "utilization_percent": util,
                "vram_total_mb": vram_total,
                "vram_used_mb": vram_used,
                "vram_percent": vram_pct,
                "temperature_c": temp,
            })
        except (ValueError, ZeroDivisionError):
            continue
    return result
