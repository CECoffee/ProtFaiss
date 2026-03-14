"""
tools/build_index_ivfpq.py — 独立 IVF-PQ 索引构建工具

使用 app.core.gpu 进行多 GPU 管理，支持：
- 自动选择最空闲 GPU（--gpu auto）或指定 GPU（--gpu 0）
- 多卡并行分片构建（受 config.yml gpu.multi_gpu_enabled 控制）
- OOM 自动 fallback 到 CPU
- tqdm 实时进度显示

用法：
  python tools/build_index_ivfpq.py --csv ../data/proteins.csv --out ../indices/10m
  python tools/build_index_ivfpq.py --csv ../data/proteins.csv --out ../indices/10m --gpu 1
"""
import argparse
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial

import faiss
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm
from transformers import AutoTokenizer, EsmModel

# Allow importing app modules when run from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import ESM2_MODEL_DIR
from app.core.config_loader import get as cfg_get
from app.core.gpu import (
    get_available_devices, get_encoding_device,
    create_faiss_gpu_resources, log_gpu_status,
)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Build sharded IVF-PQ FAISS index from CSV")
parser.add_argument("--csv", default="../data/proteins_mock_10m.csv", help="Input CSV file")
parser.add_argument("--seq-col", default="sequence", help="Column name for sequences")
parser.add_argument("--out", default="../indices/10m", help="Output directory for shards")
parser.add_argument("--gpu", default="auto", help='"auto" | GPU device id (int) | "cpu"')
parser.add_argument("--nlist", type=int, default=None, help="IVF nlist (default: from config.yml)")
parser.add_argument("--pq-m", type=int, default=None, help="PQ sub-spaces (default: from config.yml)")
parser.add_argument("--nbits", type=int, default=8, help="PQ bits per sub-space")
parser.add_argument("--nprobe", type=int, default=16, help="nprobe for search")
parser.add_argument("--batch-size", type=int, default=None, help="Encoding batch size (default: from config.yml)")
parser.add_argument("--max-per-shard", type=int, default=None, help="Max vectors per shard (default: from config.yml)")
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NLIST = args.nlist or cfg_get("build", "ivfpq_nlist", 256)
PQ_M = args.pq_m or cfg_get("build", "ivfpq_m", 64)
NBITS = args.nbits
NPROBE = args.nprobe
ENCODING_BATCH = args.batch_size or cfg_get("build", "encoding_batch_size", 32)
MAX_PER_SHARD = args.max_per_shard or cfg_get("build", "max_per_shard", 1_000_000)
ADD_BATCH_SIZE = cfg_get("build", "add_batch_size", 200_000)
TRAIN_SAMPLE = max(NLIST * 40, min(200_000, MAX_PER_SHARD))
D = 1280

# ---------------------------------------------------------------------------
# GPU setup
# ---------------------------------------------------------------------------

log_gpu_status()

if args.gpu == "auto":
    enc_device = get_encoding_device()
    faiss_devices = get_available_devices()
elif args.gpu == "cpu":
    enc_device = torch.device("cpu")
    faiss_devices = []
else:
    gpu_id = int(args.gpu)
    enc_device = torch.device(f"cuda:{gpu_id}")
    faiss_devices = [gpu_id]

print(f"[config] encoding_device={enc_device}, faiss_devices={faiss_devices or ['cpu']}")
print(f"[config] nlist={NLIST}, pq_m={PQ_M}, nbits={NBITS}, batch={ENCODING_BATCH}, max_per_shard={MAX_PER_SHARD}")

# ---------------------------------------------------------------------------
# Model init
# ---------------------------------------------------------------------------

print(f"Loading ESM2 model from {ESM2_MODEL_DIR} ...")
tokenizer = AutoTokenizer.from_pretrained(ESM2_MODEL_DIR, local_files_only=True)
model = EsmModel.from_pretrained(ESM2_MODEL_DIR, local_files_only=True)
model.to(enc_device)
model.eval()

# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _collate(batch, tok):
    return tok(batch, return_tensors="pt", padding=True, max_length=2048, truncation=True)


def encode_sequences(sequences: list) -> np.ndarray:
    """OOM-safe batch encoding with tqdm progress."""
    device = next(model.parameters()).device
    embeddings = []
    batch_size = ENCODING_BATCH
    total = len(sequences)
    done = 0

    with tqdm(total=total, desc="Encoding", unit="seq") as pbar:
        i = 0
        while i < total:
            batch_seqs = sequences[i: i + batch_size]
            batch = _collate(batch_seqs, tokenizer)
            input_ids = batch["input_ids"]
            attention_mask = batch["attention_mask"]

            for attempt in range(4):
                try:
                    ids = input_ids.to(device)
                    mask = attention_mask.to(device)
                    with torch.no_grad():
                        outputs = model(input_ids=ids, attention_mask=mask)
                    features = outputs.last_hidden_state
                    masked = features * mask.unsqueeze(2)
                    pooled = masked.sum(dim=1) / mask.sum(dim=1, keepdim=True)
                    embeddings.append(pooled.detach().cpu().numpy())
                    done += len(batch_seqs)
                    pbar.update(len(batch_seqs))
                    pbar.set_postfix({"batch": batch_size})
                    break
                except torch.cuda.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    batch_size = max(1, batch_size // 2)
                    print(f"\n[OOM] Reducing batch_size to {batch_size}")
                    batch_seqs = sequences[i: i + batch_size]
                    batch = _collate(batch_seqs, tokenizer)
                    input_ids = batch["input_ids"]
                    attention_mask = batch["attention_mask"]

            i += len(batch_seqs)

    return np.concatenate(embeddings, axis=0).astype("float32")


# ---------------------------------------------------------------------------
# Single-shard IVF-PQ build
# ---------------------------------------------------------------------------

def build_shard(shard_id: int, vecs: np.ndarray, gpu_id: int, out_dir: str) -> str:
    n = vecs.shape[0]
    quantizer = faiss.IndexFlatL2(D)
    index_cpu = faiss.IndexIVFPQ(quantizer, D, NLIST, PQ_M, NBITS)
    index_cpu.nprobe = NPROBE

    sample_size = min(n, TRAIN_SAMPLE)
    if sample_size < NLIST:
        sample_size = n
    perm = np.random.permutation(n)[:sample_size]
    train_vecs = np.ascontiguousarray(vecs[perm])

    use_gpu = gpu_id >= 0 and torch.cuda.is_available()
    if use_gpu:
        res = create_faiss_gpu_resources(gpu_id)
        try:
            index_gpu = faiss.index_cpu_to_gpu(res, gpu_id, index_cpu)
            print(f"[shard {shard_id}] Training on GPU {gpu_id} ({sample_size} samples)...")
            index_gpu.train(train_vecs)

            added = 0
            with tqdm(total=n, desc=f"shard {shard_id} adding", unit="vec", leave=False) as pbar:
                for i in range(0, n, ADD_BATCH_SIZE):
                    batch = np.ascontiguousarray(vecs[i: i + ADD_BATCH_SIZE])
                    index_gpu.add(batch)
                    added += batch.shape[0]
                    pbar.update(batch.shape[0])
                    pbar.set_postfix({"added": f"{added}/{n}"})

            index_cpu = faiss.index_gpu_to_cpu(index_gpu)
            index_cpu.nprobe = NPROBE
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            print(f"[shard {shard_id}] OOM on GPU {gpu_id}, falling back to CPU.")
            use_gpu = False

    if not use_gpu:
        print(f"[shard {shard_id}] Training on CPU ({sample_size} samples)...")
        index_cpu.train(train_vecs)
        added = 0
        with tqdm(total=n, desc=f"shard {shard_id} adding (CPU)", unit="vec", leave=False) as pbar:
            for i in range(0, n, ADD_BATCH_SIZE):
                batch = np.ascontiguousarray(vecs[i: i + ADD_BATCH_SIZE])
                index_cpu.add(batch)
                added += batch.shape[0]
                pbar.update(batch.shape[0])

    shard_path = os.path.join(out_dir, f"shard_{shard_id:03d}.faiss")
    faiss.write_index(index_cpu, shard_path)
    print(f"[shard {shard_id}] Saved to {shard_path}")
    return shard_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_sharded_faiss(csv_path: str, seq_column: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    df = pd.read_csv(csv_path)
    if seq_column not in df.columns:
        raise ValueError(f"Column '{seq_column}' not found in CSV")

    n = len(df)
    n_shards = math.ceil(n / MAX_PER_SHARD)
    shard_size = math.ceil(n / n_shards)
    print(f"Total: {n} sequences, {n_shards} shards, ~{shard_size} per shard")

    start_all = time.time()

    # Encode all sequences
    sequences = df[seq_column].tolist()
    all_vecs = encode_sequences(sequences)
    model.cpu()
    torch.cuda.empty_cache()
    print(f"Encoding done: {all_vecs.shape[0]} vectors")

    # Build shards (parallel if multi-GPU)
    shard_chunks = [
        np.ascontiguousarray(all_vecs[sid * shard_size: (sid + 1) * shard_size])
        for sid in range(n_shards)
        if all_vecs[sid * shard_size: (sid + 1) * shard_size].shape[0] > 0
    ]

    devices = faiss_devices if faiss_devices else [-1]
    max_workers = max(1, len(devices))

    print(f"Building {len(shard_chunks)} shards with {max_workers} worker(s) on devices {devices} ...")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(build_shard, sid, chunk, devices[sid % len(devices)], output_dir): sid
            for sid, chunk in enumerate(shard_chunks)
        }
        for fut in as_completed(futures):
            fut.result()

    del all_vecs
    print(f"\nAll done. Total: {n} sequences, elapsed: {time.time() - start_all:.1f}s")


if __name__ == "__main__":
    build_sharded_faiss(args.csv, args.seq_col, args.out)
