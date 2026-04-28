"""
FAISS shard loader with LRU multi-dataset cache.

Each dataset's shards are loaded on demand and cached in an OrderedDict.
When the cache is full, the least-recently-used dataset is evicted (GPU resources freed).
"""
from collections import OrderedDict
from typing import List, Callable, Optional, Tuple
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import faiss
import numpy as np
import torch

from .config import FAISS_SHARD_DIR, get_faiss_search_workers, get_faiss_nprobe
from app.core import config_loader

# ---------------------------------------------------------------------------
# ShardSet: holds all shards for one dataset
# ---------------------------------------------------------------------------

@dataclass
class ShardSet:
    shards: List[faiss.Index] = field(default_factory=list)
    locks: List[threading.Lock] = field(default_factory=list)
    gpu_resources: List = field(default_factory=list)  # (dev_id, res) or None


# ---------------------------------------------------------------------------
# LRU cache
# ---------------------------------------------------------------------------

_CACHE: OrderedDict[str, ShardSet] = OrderedDict()
_CACHE_LOCK = threading.RLock()


def _get_max_cached() -> int:
    return config_loader.get("scheduler", "max_cached_datasets", 4)


def _unload_shard_set(shard_set: ShardSet) -> None:
    """Release GPU resources for a ShardSet."""
    for res_entry in shard_set.gpu_resources:
        if res_entry is not None:
            try:
                # faiss GPU resources are freed when the Python object is GC'd
                pass
            except Exception:
                pass
    try:
        torch.cuda.empty_cache()
    except Exception:
        pass


def _load_shard_set(shard_dir: str) -> ShardSet:
    """Load all .faiss files from shard_dir into a ShardSet."""
    shard_paths = sorted([
        os.path.join(shard_dir, f)
        for f in os.listdir(shard_dir)
        if f.endswith(".faiss")
    ])
    if not shard_paths:
        raise RuntimeError("No faiss shards found in: " + shard_dir)

    from app.core.gpu import get_available_devices, create_faiss_gpu_resources, create_gpu_cloner_options
    devices = get_available_devices()
    nprobe = get_faiss_nprobe()

    shards = []
    locks = []
    gpu_resources = []

    for i, p in enumerate(shard_paths):
        idx_cpu = faiss.read_index(p)
        loaded = False

        if devices:
            dev_id = devices[i % len(devices)]
            try:
                res = create_faiss_gpu_resources(dev_id)
                idx_gpu = faiss.index_cpu_to_gpu(res, dev_id, idx_cpu, create_gpu_cloner_options())
                idx_gpu.nprobe = nprobe
                shards.append(idx_gpu)
                gpu_resources.append((dev_id, res))
                loaded = True
            except Exception as e:
                print(f"[retriever] Shard {i} failed on GPU {dev_id}, using CPU: {e}")
                torch.cuda.empty_cache()

        if not loaded:
            shards.append(idx_cpu)
            gpu_resources.append(None)

        locks.append(threading.Lock())

    gpu_devs = [r[0] for r in gpu_resources if r is not None]
    print(f"[retriever] Loaded {len(shards)} shards from {shard_dir} on devices: {gpu_devs or ['cpu']}")
    return ShardSet(shards=shards, locks=locks, gpu_resources=gpu_resources)


def get_or_load_shards(dataset_id: str) -> ShardSet:
    """Get ShardSet from LRU cache, loading if necessary."""
    from app.core.config_loader import get_datasets_root
    index_dir = os.path.join(get_datasets_root(), dataset_id, "indices")
    with _CACHE_LOCK:
        if dataset_id in _CACHE:
            _CACHE.move_to_end(dataset_id)
            return _CACHE[dataset_id]

        # Evict LRU if cache is full
        max_cached = _get_max_cached()
        while len(_CACHE) >= max_cached:
            evicted_id, evicted_set = _CACHE.popitem(last=False)
            _unload_shard_set(evicted_set)
            print(f"[retriever] Evicted dataset {evicted_id} from shard cache")

        shard_set = _load_shard_set(index_dir)
        _CACHE[dataset_id] = shard_set
        return shard_set


def is_cached(dataset_id: str) -> bool:
    """Return True if dataset shards are currently in the LRU cache."""
    with _CACHE_LOCK:
        return dataset_id in _CACHE


def unload_dataset(dataset_id: str) -> bool:
    """Remove dataset from LRU cache and free GPU resources. Returns True if it was present."""
    with _CACHE_LOCK:
        if dataset_id not in _CACHE:
            return False
        shard_set = _CACHE.pop(dataset_id)
        _unload_shard_set(shard_set)
        print(f"[retriever] Unloaded dataset {dataset_id} from VRAM")
        return True


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_SHARDS_SWAP_LOCK = threading.RLock()


def _search_one_shard(index, lock, query_vector, top_k):
    try:
        with lock:
            D, I = index.search(query_vector, top_k)
        return D[0].tolist(), I[0].tolist()
    except Exception as e:
        print("Shard error:", e)
        return [], []


def blocking_faiss_search(
    query_vector,
    top_k: int,
    progress_cb: Optional[Callable] = None,
    dataset_id: Optional[str] = None,
):
    """Blocking search across shards using the LRU cache."""
    import time as _time
    load_start = _time.time()
    if not dataset_id:
        raise RuntimeError("dataset_id is required")
    shard_set = get_or_load_shards(dataset_id)
    shards = shard_set.shards
    locks = shard_set.locks
    load_seconds = _time.time() - load_start

    if not shards:
        raise RuntimeError("No FAISS shards loaded. Activate a dataset first.")

    if isinstance(query_vector, torch.Tensor):
        if query_vector.is_cuda:
            query_cpu = query_vector.detach().cpu().pin_memory()
        else:
            query_cpu = query_vector.detach()
        query_np = np.asarray(query_cpu, dtype=np.float32)
    else:
        query_np = query_vector.astype('float32', copy=False)

    results = []
    total_shards = len(shards)
    completed = 0
    max_workers = min(get_faiss_search_workers(), max(1, total_shards))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(_search_one_shard, idx, locks[si], query_np, top_k)
            for si, idx in enumerate(shards)
        ]
        for fut in as_completed(futures):
            D, I = fut.result()
            if D and I:
                for d, i in zip(D, I):
                    if int(i) >= 0:
                        results.append((float(d), int(i)))
            completed += 1
            if progress_cb:
                progress_cb(completed, total_shards)

    return sorted(results, key=lambda x: x[0])[:top_k], load_seconds
