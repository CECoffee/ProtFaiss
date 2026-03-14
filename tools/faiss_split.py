"""
tools/faiss_split.py — 将一个大 FAISS 索引拆分为多个分片

支持：
- 自动多 GPU 并行构建分片（受 config.yml gpu.multi_gpu_enabled 控制）
- OOM fallback 到 CPU
- tqdm 实时进度

用法：
  python tools/faiss_split.py --src ../data/protein_index_1M.faiss --out ../indices/1m
  python tools/faiss_split.py --src ../data/protein_index_1M.faiss --out ../indices/1m --gpu cpu
"""
import argparse
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import faiss
import numpy as np
import torch
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config_loader import get as cfg_get
from app.core.gpu import get_available_devices, create_faiss_gpu_resources, log_gpu_status

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Split a FAISS index into shards")
parser.add_argument("--src", default="../data/protein_index_1M.faiss", help="Source FAISS index")
parser.add_argument("--out", default="../indices/1m", help="Output directory")
parser.add_argument("--target-per-shard", type=int, default=1_000_000)
parser.add_argument("--pq-m", type=int, default=16)
parser.add_argument("--bits", type=int, default=8)
parser.add_argument("--nprobe", type=int, default=32)
parser.add_argument("--nlist-scale", type=float, default=1000)
parser.add_argument("--train-max", type=int, default=200_000)
parser.add_argument("--gpu", default="auto", help='"auto" | GPU id (int) | "cpu"')
parser.add_argument("--use-opq", action="store_true")
args = parser.parse_args()

# ---------------------------------------------------------------------------
# GPU setup
# ---------------------------------------------------------------------------

log_gpu_status()

if args.gpu == "auto":
    faiss_devices = get_available_devices()
elif args.gpu == "cpu":
    faiss_devices = []
else:
    faiss_devices = [int(args.gpu)]

print(f"[config] faiss_devices={faiss_devices or ['cpu']}")

# ---------------------------------------------------------------------------
# Load source index and reconstruct vectors
# ---------------------------------------------------------------------------

print(f"Loading source index from {args.src} ...")
index_src = faiss.read_index(args.src)
ntotal = index_src.ntotal
d = index_src.d
print(f"Total vectors: {ntotal}, dim={d}")

print("Reconstructing all vectors into RAM ...")
vectors = np.empty((ntotal, d), dtype="float32")
for i in tqdm(range(ntotal), desc="Reconstructing"):
    vectors[i] = index_src.reconstruct(i)

# ---------------------------------------------------------------------------
# Shard build
# ---------------------------------------------------------------------------

os.makedirs(args.out, exist_ok=True)
num_shards = math.ceil(ntotal / args.target_per_shard)
real_per_shard = math.ceil(ntotal / num_shards)
print(f"Splitting into {num_shards} shards, ~{real_per_shard} vectors each")


def build_shard(shard_id: int, start: int, end: int, gpu_id: int) -> str:
    shard_vecs = vectors[start:end].astype("float32")
    n = shard_vecs.shape[0]
    nlist = max(256, int(args.nlist_scale))

    coarse = faiss.IndexFlatL2(d)
    index_cpu = faiss.IndexIVFPQ(coarse, d, nlist, args.pq_m, args.bits)
    index_cpu.nprobe = args.nprobe

    if args.use_opq:
        opq = faiss.OPQMatrix(d, args.pq_m)
        index_cpu = faiss.IndexPreTransform(opq, index_cpu)

    train_n = min(n, args.train_max)
    train_ids = np.random.choice(n, train_n, replace=False)
    train_samples = shard_vecs[train_ids]

    use_gpu = gpu_id >= 0 and torch.cuda.is_available()
    if use_gpu:
        res = create_faiss_gpu_resources(gpu_id)
        try:
            gpu_index = faiss.index_cpu_to_gpu(res, gpu_id, index_cpu)
            print(f"[shard {shard_id}] Training on GPU {gpu_id} ({train_n} samples)...")
            gpu_index.train(train_samples)
            with tqdm(total=n, desc=f"shard {shard_id} adding", unit="vec", leave=False) as pbar:
                gpu_index.add(shard_vecs)
                pbar.update(n)
            index_cpu = faiss.index_gpu_to_cpu(gpu_index)
            index_cpu.nprobe = args.nprobe
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            print(f"[shard {shard_id}] OOM on GPU {gpu_id}, falling back to CPU.")
            use_gpu = False

    if not use_gpu:
        print(f"[shard {shard_id}] Training on CPU ({train_n} samples)...")
        index_cpu.train(train_samples)
        with tqdm(total=n, desc=f"shard {shard_id} adding (CPU)", unit="vec", leave=False) as pbar:
            index_cpu.add(shard_vecs)
            pbar.update(n)

    shard_path = os.path.join(args.out, f"shard_{shard_id:03d}.faiss")
    faiss.write_index(index_cpu, shard_path)
    print(f"[shard {shard_id}] Saved to {shard_path}")
    return shard_path


devices = faiss_devices if faiss_devices else [-1]
max_workers = max(1, len(devices))

shard_jobs = [
    (sid, sid * real_per_shard, min((sid + 1) * real_per_shard, ntotal))
    for sid in range(num_shards)
]

print(f"Building {num_shards} shards with {max_workers} worker(s) ...")
with ThreadPoolExecutor(max_workers=max_workers) as ex:
    futures = {
        ex.submit(build_shard, sid, start, end, devices[sid % len(devices)]): sid
        for sid, start, end in shard_jobs
    }
    for fut in as_completed(futures):
        fut.result()

print("All shards built and saved.")
