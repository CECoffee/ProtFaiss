import faiss
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from transformers import AutoTokenizer, EsmModel
from functools import partial
from tqdm import tqdm
import time
import gc
import os

# ------------------------
# 1. 编码函数
# ------------------------
def collate_fn(batch, tokenizer):
    return tokenizer(batch, return_tensors="pt", padding=True, max_length=2048, truncation=True)

@torch.inference_mode()
def my_esm2_batch_encoder(data, tokenizer, model, batch_size=12, pooling='mean', num_workers=4):
    """对序列进行批量编码（返回 numpy 向量批次生成器）"""
    loader = DataLoader(
        data,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        collate_fn=partial(collate_fn, tokenizer=tokenizer)
    )

    for batch in tqdm(loader, desc="Encoding", dynamic_ncols=True):
        with torch.cuda.amp.autocast():  # 混合精度加速
            input_ids = batch["input_ids"].cuda(non_blocking=True)
            attention_mask = batch["attention_mask"].cuda(non_blocking=True)

            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            hidden = outputs.last_hidden_state * attention_mask.unsqueeze(2)

            if pooling == 'mean':
                pooled = hidden.sum(1) / attention_mask.sum(1, keepdim=True)
            elif pooling == 'max':
                pooled = hidden.max(1).values
            elif pooling == 'sum':
                pooled = hidden.sum(1)
            else:
                pooled = hidden

        yield pooled.detach().cpu().numpy()

        # 清理显存与CPU缓存
        del batch, outputs, hidden, pooled
        torch.cuda.empty_cache()
        gc.collect()


# ------------------------
# 2. 主流程
# ------------------------
def build_index_from_csv(
    csv_path="proteins_mock.csv",
    seq_column="sequence",
    use_cosine=False,
    batch_size=12,
    num_workers=4
):
    print("========== 蛋白质索引构建开始 ==========")
    start_time = time.time()

    # 模型加载
    print("--- 加载 ESM2 模型 ---")
    tokenizer = AutoTokenizer.from_pretrained("facebook/esm2_t33_650M_UR50D")
    model = EsmModel.from_pretrained("facebook/esm2_t33_650M_UR50D").cuda().eval()
    model.half()
    D = model.config.hidden_size  # 一般为 1280

    # 初始化 FAISS GPU 索引
    print("--- 初始化 FAISS GPU 索引 ---")
    res = faiss.StandardGpuResources()
    index_type = faiss.IndexFlatIP(D) if use_cosine else faiss.IndexFlatL2(D)
    index = faiss.index_cpu_to_gpu(res, 0, index_type)
    if use_cosine:
        print("使用 Cosine 相似度（IndexFlatIP + 向量归一化）")
    else:
        print("使用 L2 距离（IndexFlatL2）")

    # 读取 CSV
    print(f"--- 读取 CSV: {csv_path} ---")
    df = pd.read_csv(csv_path)
    if seq_column not in df.columns:
        raise ValueError(f"CSV中找不到列 '{seq_column}'")
    sequences = df[seq_column].dropna().tolist()
    print(f"共 {len(sequences)} 条序列。")

    # 批量编码 + 添加到索引
    total_added = 0
    for emb_batch in my_esm2_batch_encoder(sequences, tokenizer, model, batch_size, 'mean', num_workers):
        if use_cosine:
            faiss.normalize_L2(emb_batch)
        index.add(emb_batch)
        total_added += len(emb_batch)
        print(f"已添加 {total_added}/{len(sequences)} 条向量")

    # 保存索引
    print("--- 保存索引 ---")
    index_cpu = faiss.index_gpu_to_cpu(index)
    out_name = "protein_index_cosine.faiss" if use_cosine else "protein_index_l2.faiss"
    faiss.write_index(index_cpu, out_name)
    print(f"索引已保存至：{out_name}")

    print(f"========== 全部完成！共 {total_added} 条向量，用时 {time.time() - start_time:.2f} 秒 ==========")


# ------------------------
# 3. 主入口
# ------------------------
if __name__ == "__main__":
    build_index_from_csv(
        csv_path="src/proteins_mock.csv",
        seq_column="sequence",
        use_cosine=False,   # 若要用余弦相似度设为 True
        batch_size=12,
        num_workers=4
    )
