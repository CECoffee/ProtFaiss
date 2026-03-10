import faiss
import numpy as np
import math
import os
from tqdm import tqdm
import argparse
import multiprocessing

# ===== 参数配置（可从命令行覆盖） =====
parser = argparse.ArgumentParser()
parser.add_argument("--src_index", type=str, default="../data/protein_index_1M.faiss")
parser.add_argument("--out_dir", type=str, default="../indices/1m")
parser.add_argument("--target_per_shard", type=int, default=1_000_000)
parser.add_argument("--pq_m", type=int, default=16)                 # PQ 子空间数（16~64之间）
parser.add_argument("--bits_per_code", type=int, default=8)         # 每子空间比特数（通常 8）
parser.add_argument("--nprobe", type=int, default=32)               # 查询时访问多少倒排桶
parser.add_argument("--nlist_scale", type=float, default=1000)      # 聚类桶数约为 sqrt(N)（经验值）
parser.add_argument("--train_max", type=int, default=200_000)       # 每 shard 训练样本数上限
parser.add_argument("--use_opq", action="store_true", help="Enable OPQ preprocessing (optional)")
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args()

SRC_INDEX = args.src_index
OUT_DIR = args.out_dir
TARGET_PER_SHARD = args.target_per_shard
PQ_M = args.pq_m
BITS_PER_CODE = args.bits_per_code
NPROBE = args.nprobe
NLIST_SCALE = args.nlist_scale
TRAIN_MAX = args.train_max
USE_OPQ = args.use_opq
VERBOSE = args.verbose

os.makedirs(OUT_DIR, exist_ok=True)

# ---------- load source index and reconstruct vectors ----------
print(f"[+] Loading source index from {SRC_INDEX} ...")
index_src = faiss.read_index(SRC_INDEX)
ntotal = index_src.ntotal
d = index_src.d
print(f"[+] Total vectors: {ntotal}, dim={d}")

print("[+] Reconstructing all vectors into RAM (this may take time & memory)...")
vectors = np.empty((ntotal, d), dtype="float32")
for i in tqdm(range(ntotal)):
    vectors[i] = index_src.reconstruct(i)

# ---------- compute shards ----------
num_shards = math.ceil(ntotal / TARGET_PER_SHARD)
real_per_shard = math.ceil(ntotal / num_shards)
print(f"[+] Splitting into {num_shards} shards, each ~{real_per_shard} vectors")

# ---------- prepare GPU resources ----------
ngpu = faiss.get_num_gpus()
if ngpu == 0:
    raise RuntimeError("No GPU detected by faiss.get_num_gpus(); ensure faiss-gpu is installed and CUDA visible.")
print(f"[+] Found {ngpu} GPU(s) for FAISS training")

# Create a GPU resource per GPU (faiss.StandardGpuResources is light-weight; you can reuse)
gpu_resources = [faiss.StandardGpuResources() for _ in range(ngpu)]

# ---------- helper to build one shard on a given GPU ----------
def build_shard_on_gpu(shard_id, start, end, device_id):
    shard_vecs = vectors[start:end].astype("float32")
    shard_size = shard_vecs.shape[0]
    print(f"[GPU{device_id}] Building shard {shard_id} (vectors {start}:{end}, count={shard_size})")

    # 参数设置
    nlist = max(256, NLIST_SCALE)  # 保底 256
    print(f"[GPU{device_id}]  nlist={nlist}, PQ_M={PQ_M}, bits={BITS_PER_CODE}")

    # 1) 在 CPU 上创建一个 IndexIVFPQ 模板（尚未训练）
    coarse = faiss.IndexFlatL2(d)
    index_ivfpq_cpu = faiss.IndexIVFPQ(coarse, d, nlist, PQ_M, BITS_PER_CODE)
    index_ivfpq_cpu.nprobe = NPROBE

    # 可选：OPQ 预变换（在 CPU 上构建 OPQMatrix 并封装）
    if USE_OPQ:
        opq_matrix = faiss.OPQMatrix(d, PQ_M)
        # 将 OPQ 包入到一个 IndexPreTransform
        index_ivfpq_cpu = faiss.IndexPreTransform(opq_matrix, index_ivfpq_cpu)

    # 2) 把未训练的 CPU index 转到 GPU 上（在指定 device）
    res = gpu_resources[device_id]
    gpu_index = faiss.index_cpu_to_gpu(res, device_id, index_ivfpq_cpu)

    # 3) 训练（在 GPU 上进行）
    train_num = min(shard_size, TRAIN_MAX)
    if train_num < shard_size:
        train_ids = np.random.choice(shard_size, train_num, replace=False)
        train_samples = shard_vecs[train_ids]
    else:
        train_samples = shard_vecs

    print(f"[GPU{device_id}]  Training with {train_samples.shape[0]} samples (on GPU{device_id}) ...")
    gpu_index.train(train_samples)

    # 4) 添加所有向量（在 GPU 上）
    print(f"[GPU{device_id}]  Adding {shard_size} vectors to GPU index ...")
    gpu_index.add(shard_vecs)

    # 5) 把训练好的 GPU 索引搬回 CPU 并写盘（faiss 写盘需 CPU index）
    index_cpu_trained = faiss.index_gpu_to_cpu(gpu_index)
    index_cpu_trained.nprobe = NPROBE

    shard_path = os.path.join(OUT_DIR, f"shard_{shard_id:03d}.faiss")
    print(f"[GPU{device_id}]  Saving trained shard to {shard_path} (CPU index)")
    faiss.write_index(index_cpu_trained, shard_path)
    print(f"[GPU{device_id}]  Done shard {shard_id}")
    return shard_path

# ---------- iterate shards and optionally parallelize across GPUs ----------
shard_jobs = []
for shard_id in range(num_shards):
    start = shard_id * real_per_shard
    end = min(start + real_per_shard, ntotal)
    shard_jobs.append((shard_id, start, end))

# 我们简单地按 shard 轮询地分配到 GPU（可改为更复杂的调度）
for shard_id, start, end in shard_jobs:
    device = shard_id % ngpu
    build_shard_on_gpu(shard_id, start, end, device)

print("[✓] All shards built and saved.")
