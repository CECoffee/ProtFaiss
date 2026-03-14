from typing import List, Callable, Optional
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import faiss
import numpy as np
import torch

from .config import FAISS_SHARD_DIR, get_faiss_search_workers, get_faiss_nprobe

FAISS_SHARDS: List[faiss.Index] = []
FAISS_SHARD_LOCKS: List[threading.Lock] = []

# Per-GPU resources: list parallel to available devices
_GPU_RESOURCES: List = []

_SHARDS_SWAP_LOCK = threading.RLock()


def load_shards(shard_dir: str = None):
    """
    Load all .faiss shards into FAISS_SHARDS.
    Distributes shards across available GPUs (round-robin) when multi_gpu_enabled=true.
    Falls back to CPU for any shard that fails to load onto GPU.
    """
    global FAISS_SHARDS, FAISS_SHARD_LOCKS, _GPU_RESOURCES
    shard_dir = shard_dir or FAISS_SHARD_DIR
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

    FAISS_SHARDS.clear()
    FAISS_SHARD_LOCKS.clear()
    new_resources = []

    for i, p in enumerate(shard_paths):
        idx_cpu = faiss.read_index(p)
        loaded = False

        if devices:
            dev_id = devices[i % len(devices)]
            try:
                # Each shard gets its own StandardGpuResources — FAISS stack allocator
                # is NOT thread-safe; sharing one res across shards on the same GPU
                # causes StackDeviceMemory assertion failures under concurrent search.
                res = create_faiss_gpu_resources(dev_id)
                idx_gpu = faiss.index_cpu_to_gpu(res, dev_id, idx_cpu, create_gpu_cloner_options())
                idx_gpu.nprobe = nprobe
                FAISS_SHARDS.append(idx_gpu)
                new_resources.append((dev_id, res))
                loaded = True
            except Exception as e:
                print(f"[retriever] Shard {i} failed to load on GPU {dev_id}, using CPU: {e}")
                torch.cuda.empty_cache()

        if not loaded:
            FAISS_SHARDS.append(idx_cpu)
            new_resources.append(None)

        FAISS_SHARD_LOCKS.append(threading.Lock())

    _GPU_RESOURCES = new_resources
    gpu_devs = [r[0] for r in new_resources if r is not None]
    print(f"[retriever] Loaded {len(FAISS_SHARDS)} shards across devices: {gpu_devs or ['cpu']}")


def swap_active_dataset(index_dir: str) -> int:
    """Reload shards from index_dir. Thread-safe. Returns number of shards loaded."""
    with _SHARDS_SWAP_LOCK:
        load_shards(index_dir)
    return len(FAISS_SHARDS)


def _search_one_shard(index, query_vector, top_k, shard_idx=None):
    try:
        lock = FAISS_SHARD_LOCKS[shard_idx]
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
):
    """
    Blocking search across all loaded shards.
    Raises RuntimeError if no shards are loaded.
    Returns sorted [(distance, id), ...] up to top_k.
    Optional progress_cb(completed, total) called after each shard completes.
    """
    if not FAISS_SHARDS:
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
    total_shards = len(FAISS_SHARDS)
    completed = 0
    max_workers = min(get_faiss_search_workers(), max(1, total_shards))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(_search_one_shard, idx, query_np, top_k, si)
            for si, idx in enumerate(FAISS_SHARDS)
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

    return sorted(results, key=lambda x: x[0])[:top_k]
