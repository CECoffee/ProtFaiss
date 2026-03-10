from functools import partial

import faiss
import numpy as np
import psycopg2
import psycopg2.extras # 用于服务器端游标
import time
import sys
from transformers import AutoTokenizer, EsmModel
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm
import os

def collate_fn(batch, tokenizer):
    return tokenizer(batch, return_tensors="pt", padding=True, max_length=2048, truncation=True)

def my_esm2_batch_encoder(data, batch_size=12, pooling='mean', num_workers=12):
    tokenizer = AutoTokenizer.from_pretrained("facebook/esm2_t33_650M_UR50D")
    model = EsmModel.from_pretrained("facebook/esm2_t33_650M_UR50D")
    model.cuda()
    model.eval()

    embeddings = []

    # 使用 partial，把 tokenizer 绑定进去，生成可 pickle 的函数
    eval_loader = DataLoader(
        data,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        collate_fn=partial(collate_fn, tokenizer=tokenizer)
    )

    with torch.no_grad():
        for batch in tqdm(eval_loader):
            input_ids = batch["input_ids"].cuda()
            attention_mask = batch["attention_mask"].cuda()
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            features = outputs.last_hidden_state
            masked_features = features * attention_mask.unsqueeze(2)
            sum_features = torch.sum(masked_features, dim=1)

            if pooling == 'mean':
                pooled_features = sum_features / attention_mask.sum(dim=1, keepdim=True)
            elif pooling == 'max':
                pooled_features = torch.max(masked_features, dim=1).values
            elif pooling == 'sum':
                pooled_features = sum_features
            else:
                pooled_features = features

            torch.cuda.empty_cache()
            embeddings.append(pooled_features.detach().cpu().numpy())

    embeddings = np.concatenate(embeddings, axis=0)
    return embeddings

# --- 2. 数据库配置 ---
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "protein_db",
    "user": "postgres",
    "password": "0909" # [!] 替换为您的密码
}

# --- 3. FAISS 索引参数 ---
D = 1280                # 维度 (ESM2)
# [修改]：IndexFlatL2 不需要 nlist, m, nbits

# --- 4. 批处理大小 ---
ENCODING_BATCH_SIZE = 512
# --- 5. 主函数 ---
# --- 5. 主函数 ---
def build_index():
    
    print("--- 步骤 1: 初始化 FAISS 索引 (IndexFlatL2) ---")
    index = faiss.IndexFlatL2(D)
    print("索引初始化完毕。")

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("数据库连接成功。")
    except psycopg2.Error as e:
        print(f"数据库连接失败: {e}", file=sys.stderr)
        return

    # --- [已删除] 步骤 2: 训练 (Training) ---

    # --- 步骤 3: 填充 (Populating) ---
    print("--- 步骤 3: 开始填充索引 (处理所有序列) ---")
    
    # [!] 移除这一行:
    # conn.autocommit = True 
    
    total_added = 0
    start_time = time.time()
    
    # [修改]：我们现在在默认事务中，
    # 使用 'with' 块来自动管理游标和事务的生命周期
    try:
        # 'with conn' 会自动开始一个事务，
        # 'with conn.cursor' 会自动创建和关闭游标
        with conn:
            with conn.cursor('population_cursor', cursor_factory=psycopg2.extras.DictCursor) as cursor:
                
                # [修改]：我们不再需要 'DECLARE'，
                # 因为命名游标在 'with conn.cursor(...)' 时已自动创建。
                # 我们也不需要 'WITH (HOLD)'，因为我们在一个事务中完成所有读取。
                cursor.execute("SELECT sequence FROM proteins ORDER BY id")

                while True:
                    # [修改]：使用 'fetchmany' 效率更高
                    rows = cursor.fetchmany(ENCODING_BATCH_SIZE)
                    
                    if not rows:
                        break # 迭代完成
                        
                    sequences_batch = [row['sequence'] for row in rows]
                    
                    # (A) 编码 (GPU)
                    embeddings_batch = my_esm2_batch_encoder(sequences_batch)
                    
                    # (B) 添加到 FAISS
                    index.add(embeddings_batch)
                    
                    total_added += len(rows)
                    if total_added % (ENCODING_BATCH_SIZE * 10) == 0:
                        print(f"已添加 {total_added} 条向量...") 

    except Exception as e:
        print(f"处理批次时出错: {e}", file=sys.stderr)
        conn.rollback() # 出错时回滚
        conn.close()
        return # 提前退出

    end_time = time.time()
    print(f"索引填充完毕。总计 {index.ntotal} 条向量。耗时: {end_time - start_time:.2f} 秒。")
    
    # --- 步骤 4: 保存到磁盘 ---
    print("--- 步骤 4: 正在将索引写入磁盘 (protein_index.faiss)... ---")
    faiss.write_index(index, "protein_index.faiss") 
    print("索引保存成功！")
    
    # --- 清理 ---
    # 'with' 块已经自动处理了事务 (提交或回滚) 和游标
    conn.close() # 我们只需要关闭连接
    print("数据库连接已关闭。")

if __name__ == "__main__":
    build_index()