from functools import partial
import faiss
import numpy as np
import pandas as pd
import time
from transformers import AutoTokenizer, EsmModel
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm
import os
import math

# ------------------------
# CONFIG（可按需调整）
# ------------------------
D = 1280                # ESM2 embedding 维度
ENCODING_BATCH = 64    # ESM2 编码批次（可根据 GPU 显存调小）
MAX_PER_SHARD = 1000000  # 每个分片最大序列数（你已经有分片逻辑）
N_LIST = 4096           # IVF 的 coarse centroids 数量（可调）
M = 64                  # PQ 的子量化数
NBITS = 8               # 每子空间位数
TRAIN_SAMPLE_SIZE = 200_000  # 用于训练 IVFPQ 的样本数（从每个分片中抽样）
ADD_BATCH_SIZE = 200_000     # 每次向 GPU 索引 add 的向量数（避免 OOM）
GPU_ID = 0              # 使用哪个 GPU（多 GPU 可扩展）
USE_HNSW_QUANTIZER = False  # 是否使用 HNSW 作为 coarse quantizer（若 True，可能需要检查 faiss-gpu 支持）

model_dir = "../models/esm2"

tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
model = EsmModel.from_pretrained(model_dir, local_files_only=True)
# ------------------------
# 1. ESM2编码函数（保持原逻辑）
# ------------------------
def collate_fn(batch, tokenizer):
    return tokenizer(batch, return_tensors="pt", padding=True, max_length=2048, truncation=True)

def my_esm2_batch_encoder(data, batch_size=ENCODING_BATCH, pooling='mean', num_workers=4):
    """
    data: list[str] of sequences
    返回: np.ndarray (N, D) dtype=float32
    """

    embeddings = []
    eval_loader = DataLoader(
        data,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        collate_fn=partial(collate_fn, tokenizer=tokenizer)
    )

    with torch.no_grad():
        for batch in tqdm(eval_loader, desc="Encoding"):
            input_ids = batch["input_ids"].cuda()
            attention_mask = batch["attention_mask"].cuda()
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            features = outputs.last_hidden_state  # (B, L, D)
            masked_features = features * attention_mask.unsqueeze(2)
            sum_features = torch.sum(masked_features, dim=1)

            if pooling == 'mean':
                pooled_features = sum_features / attention_mask.sum(dim=1, keepdim=True)
            elif pooling == 'max':
                pooled_features = torch.max(masked_features, dim=1).values
            elif pooling == 'sum':
                pooled_features = sum_features
            else:
                pooled_features = features[:, 0, :]  # 默认取第一个 token

            embeddings.append(pooled_features.detach().cpu().numpy())

    embeddings = np.concatenate(embeddings, axis=0).astype('float32')
    torch.cuda.empty_cache()
    return embeddings

# ------------------------
# 2. IVFPQ 索引构建（GPU 训练 + GPU 添加）
# ------------------------
def build_ivfpq_index_on_gpu(vectors: np.ndarray,
                             nlist=N_LIST,
                             m=M,
                             nbits=NBITS,
                             gpu_id=GPU_ID,
                             train_sample_size=TRAIN_SAMPLE_SIZE,
                             add_batch_size=ADD_BATCH_SIZE,
                             nprobe=16):
    """
    在 GPU 上训练并添加数据的 IVFPQ 构建函数。
    vectors: np.ndarray (N, D) float32
    返回: CPU 索引（faiss.Index）已训练并包含所有向量，适合写入磁盘。
    """

    assert vectors.dtype == np.float32, "vectors must be float32"
    N, D_local = vectors.shape
    assert D_local == D, f"输入维度 {D_local} 不等于 D={D}"

    # 1) coarse quantizer
    if USE_HNSW_QUANTIZER:
        # 注意：某些 faiss-gpu 构建/版本对 HNSW coarse quantizer 的支持有限，如果遇到问题请改为 IndexFlatL2
        quantizer = faiss.IndexHNSWFlat(D, 32)
    else:
        quantizer = faiss.IndexFlatL2(D)

    # 2) 在 CPU 上创建 IndexIVFPQ
    index_cpu = faiss.IndexIVFPQ(quantizer, D, nlist, m, nbits)
    index_cpu.nprobe = nprobe

    # 3) 转到 GPU（创建 GPU 资源）
    res = faiss.StandardGpuResources()
    # 如果有多卡场景，这里可创建多个 resources 或使用指定 device map
    print("将索引从 CPU 转到 GPU ...")
    index_gpu = faiss.index_cpu_to_gpu(res, gpu_id, index_cpu)

    # 4) 训练：选取样本用于训练（随机抽样）
    sample_size = min(N, train_sample_size)
    if sample_size < nlist:
        raise ValueError(f"train sample ({sample_size}) must be >= nlist ({nlist})")
    # 随机采样以避免顺序偏差
    perm = np.random.permutation(N)[:sample_size]
    train_samples = vectors[perm].copy()
    print(f"GPU 上训练索引：样本数 {sample_size} / {N}")
    index_gpu.train(train_samples)

    # 5) 分批 add 到 GPU 索引（避免一次性 OOM）
    print("开始分批将向量 add 到 GPU 索引 ...")
    added = 0
    for i in tqdm(range(0, N, add_batch_size), desc="Adding batches"):
        batch = vectors[i: i + add_batch_size]
        # 保证 C-contiguous
        if not batch.flags['C_CONTIGUOUS']:
            batch = np.ascontiguousarray(batch)
        index_gpu.add(batch)  # 在 GPU 上添加
        added += batch.shape[0]
        # 释放显存碎片
    print(f"全部 add 完成，总计 {added} 向量")

    # 6) 把 GPU 索引搬回 CPU 以便保存
    print("将 GPU 索引迁回 CPU 并返回 ...")
    index_cpu_final = faiss.index_gpu_to_cpu(index_gpu)
    index_cpu_final.nprobe = nprobe
    return index_cpu_final


def build_ivfpq_index_on_cpu(vectors: np.ndarray,
                             nlist=N_LIST,
                             m=M,
                             nbits=NBITS,
                             train_sample_size=TRAIN_SAMPLE_SIZE,
                             add_batch_size=ADD_BATCH_SIZE,
                             nprobe=16):
    """
    在 CPU 上训练并添加数据的 IVFPQ 构建函数（不使用 GPU）。
    vectors: np.ndarray (N, D) float32
    返回: CPU 索引（faiss.Index）已训练并包含所有向量，适合写入磁盘。
    """
    assert vectors.dtype == np.float32, "vectors must be float32"
    N, D_local = vectors.shape
    assert D_local == D, f"输入维度 {D_local} 不等于 D={D}"

    # 1) coarse quantizer（CPU 上）
    if USE_HNSW_QUANTIZER:
        # 注意：IndexHNSWFlat 在 CPU 上也是支持的
        quantizer = faiss.IndexHNSWFlat(D, 32)
    else:
        quantizer = faiss.IndexFlatL2(D)

    # 2) 在 CPU 上创建 IndexIVFPQ（注意：quantizer 已在 CPU）
    index_cpu = faiss.IndexIVFPQ(quantizer, D, nlist, m, nbits)
    index_cpu.nprobe = nprobe

    # 3) 训练：选取样本用于训练（随机抽样）
    sample_size = min(N, train_sample_size)
    if sample_size < nlist:
        raise ValueError(f"train sample ({sample_size}) must be >= nlist ({nlist})")
    perm = np.random.permutation(N)[:sample_size]
    train_samples = vectors[perm].copy()
    # 确保 C-contiguous
    if not train_samples.flags['C_CONTIGUOUS']:
        train_samples = np.ascontiguousarray(train_samples)

    print(f"CPU 上训练索引：样本数 {sample_size} / {N}")
    index_cpu.train(train_samples)  # 在 CPU 上训练

    # 4) 分批 add 到 CPU 索引（避免一次性 OOM）
    print("开始分批将向量 add 到 CPU 索引 ...")
    added = 0
    for i in tqdm(range(0, N, add_batch_size), desc="Adding batches (CPU)"):
        batch = vectors[i: i + add_batch_size]
        if not batch.flags['C_CONTIGUOUS']:
            batch = np.ascontiguousarray(batch)
        index_cpu.add(batch)
        added += batch.shape[0]
    print(f"全部 add 完成，总计 {added} 向量")

    # 5) 返回已经训练并填充的 CPU 索引
    index_cpu.nprobe = nprobe
    return index_cpu

# ------------------------
# 3. 主流程：自动分片并构建每个分片索引
# ------------------------
def build_sharded_faiss(csv_path="proteins.csv", seq_column="sequence", output_dir="../indices/10m"):
    os.makedirs(output_dir, exist_ok=True)
    df = pd.read_csv(csv_path)
    n = len(df)
    if seq_column not in df.columns:
        raise ValueError(f"CSV 中找不到列 '{seq_column}'")

    # 动态计算分片数量
    n_shards = math.ceil(n / MAX_PER_SHARD)
    shard_size = math.ceil(n / n_shards)
    print(f"总数据量 {n}，分片 {n_shards}，每片约 {shard_size} 条。")

    start_all = time.time()
    total = 0

    for shard_id in range(n_shards):
        shard_df = df.iloc[shard_id * shard_size : (shard_id + 1) * shard_size]
        print(f"\n=== 构建分片 {shard_id+1}/{n_shards} （{len(shard_df)} 条） ===")

        model.cuda()
        model.eval()

        # 1) 编码（按小批次）
        all_vecs = []
        for i in range(0, len(shard_df), ENCODING_BATCH):
            seqs = shard_df[seq_column].iloc[i:i+ENCODING_BATCH].tolist()
            emb = my_esm2_batch_encoder(seqs)
            all_vecs.append(emb)
        all_vecs = np.concatenate(all_vecs, axis=0).astype('float32')
        model.cpu()
        torch.cuda.empty_cache()
        print(f"分片 {shard_id} 编码完成，向量数 {all_vecs.shape[0]}")

        # 2) 在 GPU 上训练并构建 IVFPQ（训练 + add 都在 GPU 上完成）
        index = build_ivfpq_index_on_gpu(
            all_vecs,
            nlist=N_LIST,
            m=M,
            nbits=NBITS,
            gpu_id=GPU_ID,
            train_sample_size=TRAIN_SAMPLE_SIZE,
            add_batch_size=ADD_BATCH_SIZE,
            nprobe=16
        )

        # 3) 保存索引到磁盘（CPU 索引）
        shard_path = os.path.join(output_dir, f"shard_{shard_id:03d}.faiss")
        faiss.write_index(index, shard_path)
        print(f"✅ 已保存 {shard_path}")

        total += len(shard_df)
        # 清理
        del all_vecs
        torch.cuda.empty_cache()

    print(f"\n全部完成，共 {total} 条，耗时 {time.time() - start_all:.2f} 秒。")

# ------------------------
# 4. 入口
# ------------------------
if __name__ == "__main__":
    build_sharded_faiss("../data/proteins_mock_10m.csv", seq_column="sequence")
