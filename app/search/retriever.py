from typing import List, Tuple
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import faiss
import numpy as np
import torch

from .config import FAISS_SHARD_DIR, FAISS_SEARCH_WORKERS

FAISS_SHARDS: List[faiss.Index] = []
FAISS_SHARD_LOCKS: List[threading.Lock] = []
GPU_RESOURCES = None

_SHARDS_SWAP_LOCK = threading.RLock()


def load_shards(shard_dir: str = None):
    """Load all .faiss shards into FAISS_SHARDS (CPU or GPU). Raises if none found."""
    global FAISS_SHARDS, FAISS_SHARD_LOCKS, GPU_RESOURCES
    shard_dir = shard_dir or FAISS_SHARD_DIR
    shard_paths = sorted([
        os.path.join(shard_dir, f)
        for f in os.listdir(shard_dir)
        if f.endswith(".faiss")
    ])
    if not shard_paths:
        raise RuntimeError("No faiss shards found in: " + shard_dir)

    GPU_RESOURCES = faiss.StandardGpuResources() if torch.cuda.is_available() else None

    FAISS_SHARDS.clear()
    FAISS_SHARD_LOCKS.clear()

    for i, p in enumerate(shard_paths):
        idx_cpu = faiss.read_index(p)
        if torch.cuda.is_available():
            idx_gpu = faiss.index_cpu_to_gpu(GPU_RESOURCES, i % torch.cuda.device_count(), idx_cpu)
            idx_gpu.nprobe = 8
            FAISS_SHARDS.append(idx_gpu)
        else:
            FAISS_SHARDS.append(idx_cpu)
        FAISS_SHARD_LOCKS.append(threading.Lock())


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


def blocking_faiss_search(query_vector, top_k: int):
    """
    Blocking search across all loaded shards.
    Raises RuntimeError if no shards are loaded.
    Returns sorted [(distance, id), ...] up to top_k.
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
    max_workers = min(FAISS_SEARCH_WORKERS, max(1, len(FAISS_SHARDS)))
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

    return sorted(results, key=lambda x: x[0])[:top_k]
