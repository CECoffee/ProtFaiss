import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import faiss
import numpy as np
import gradio as gr
import psycopg2
import psycopg2.pool # [!] 关键：使用连接池以提高 Web 服务性能
import time
import sys
import re # 用于清理输入的序列
from transformers import AutoTokenizer, EsmModel
import torch
# [移除]：我们不再需要 DataLoader 或 tqdm
# from torch.utils.data import DataLoader
# from tqdm import tqdm

# --- 1. 全局资源 (服务启动时加载一次) ---
FAISS_INDEX = None
ESM2_TOKENIZER = None # [!] 在全局加载
ESM2_MODEL = None     # [!] 在全局加载
DB_CONN_POOL = None

# --- 2. 数据库配置 ---
# [!] 请在此处修改您的数据库连接信息
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "protein_db",
    "user": "postgres",
    "password": "0909" # [!] 替换为您的密码
}

print("--- 服务启动中 ---")

try:
    # 3.1 加载 FAISS 分片索引
    print("正在加载分片 FAISS 索引")
    FAISS_SHARDS = []
    shard_dir = "src/faiss_shards"
    shard_paths = sorted([
        os.path.join(shard_dir, f) for f in os.listdir(shard_dir)
        if f.endswith(".faiss")
    ])

    if not shard_paths:
        raise RuntimeError("未在 faiss_shards/ 目录中找到任何索引文件")

    for path in shard_paths:
        idx = faiss.read_index(path)
        FAISS_SHARDS.append(idx)
        print(f"  加载分片: {path}, ntotal={idx.ntotal}")

    print(f"共加载 {len(FAISS_SHARDS)} 个索引分片，总向量数 = {sum(x.ntotal for x in FAISS_SHARDS)}")

    # 3.2 加载 ESM2 模型
    print("正在加载 ESM2 Tokenizer 和 Model (这可能需要一些时间)...")
    ESM2_TOKENIZER = AutoTokenizer.from_pretrained("facebook/esm2_t33_650M_UR50D")
    ESM2_MODEL = EsmModel.from_pretrained("facebook/esm2_t33_650M_UR50D")
    ESM2_MODEL.cuda()
    ESM2_MODEL.eval()
    print("ESM2 模型加载完毕。")

    # 3.3 数据库连接池
    print("正在创建数据库连接池...")
    DB_CONN_POOL = psycopg2.pool.SimpleConnectionPool(
        1,
        5,
        **DB_CONFIG
    )
    print("数据库连接池创建成功。")

except Exception as e:
    print(f"服务启动失败: {e}", file=sys.stderr)
    sys.exit(1)


# --- 高效编码器 ---
def my_esm2_encoder(sequence_str, pooling='mean'):
    inputs = ESM2_TOKENIZER(
        sequence_str,
        return_tensors="pt",
        max_length=2048,
        truncation=True
    )

    with torch.no_grad():
        input_ids = inputs["input_ids"].cuda()
        attention_mask = inputs["attention_mask"].cuda()
        outputs = ESM2_MODEL(input_ids=input_ids, attention_mask=attention_mask)
        features = outputs.last_hidden_state
        masked_features = features * attention_mask.unsqueeze(2)
        sum_features = torch.sum(masked_features, dim=1)

        if pooling == 'mean':
            pooled_features = sum_features / attention_mask.sum(dim=1, keepdim=True)
        elif pooling == 'max':
            pooled_features, _ = torch.max(masked_features, dim=1)
        elif pooling == 'sum':
            pooled_features = sum_features
        else:
            pooled_features = sum_features / attention_mask.sum(dim=1, keepdim=True)

        return pooled_features.detach().cpu().numpy().astype('float32')


# --- 并行搜索辅助函数 ---
def _search_one_shard(index, query_vector, top_k):
    try:
        D, I = index.search(query_vector, top_k)
        return D[0], I[0]
    except Exception as e:
        print(f"分片检索错误: {e}")
        return [], []


# --- 核心搜索函数 ---
def handle_search_query(query_sequence, top_k=5):
    if not query_sequence:
        return "请输入查询序列。"

    cleaned_sequence = re.sub(r"^>.*\n", "", query_sequence, flags=re.MULTILINE)
    cleaned_sequence = re.sub(r"\s", "", cleaned_sequence).upper()
    if not cleaned_sequence:
        return "输入的序列为空或格式无效。"

    top_k = int(top_k)
    conn = None

    try:
        start_time = time.time()

        # 1. ESM2 编码
        query_vector = my_esm2_encoder(cleaned_sequence)
        embed_time = time.time()

        # 2. 并行检索所有 FAISS 分片
        results = []
        with ThreadPoolExecutor(max_workers=min(8, len(FAISS_SHARDS))) as ex:
            futures = [ex.submit(_search_one_shard, idx, query_vector, top_k) for idx in FAISS_SHARDS]
            for fut in as_completed(futures):
                D, I = fut.result()
                if len(D) > 0:
                    for d, i in zip(D, I):
                        results.append((float(d), int(i)))

        # 3. 聚合所有分片结果
        if not results:
            return "在所有索引分片中未找到结果。"

        results.sort(key=lambda x: x[0])
        merged_results = results[:top_k]
        faiss_time = time.time()

        result_ids_list = [i for _, i in merged_results]

        # 4. 数据库查询
        conn = DB_CONN_POOL.getconn()
        cursor = conn.cursor()
        cursor.execute("""
                       SELECT id, original_header, sequence, ph_processed, ko_number, ec_number
                       FROM "proteins_mock_1M"
                       WHERE id = ANY (%s)
                       """, (result_ids_list,))
        db_results = cursor.fetchall()
        cursor.close()
        db_time = time.time()

        # 5. 格式化输出
        results_map = {row[0]: row for row in db_results}
        output = f"""
        查询耗时: **{(db_time - start_time) * 1000:.0f} ms**
        (编码: {(embed_time - start_time) * 1000:.0f} ms | 分片检索: {(faiss_time - embed_time) * 1000:.0f} ms | 数据库: {(db_time - faiss_time) * 1000:.0f} ms)
        
        """

        for i, (dist, result_id) in enumerate(merged_results):
            if result_id in results_map:
                row = results_map[result_id]
                output += f"### Top {i + 1} (ID: {row[0]})\n"
                output += f"- **Header:** `{row[1]}`\n"
                output += f"- **FAISS 距离:** `{dist:.4f}`\n"
                output += f"- **KO:** `{row[4] or 'N/A'}`\n"
                output += f"- **EC:** `{row[5] or 'N/A'}`\n"
                output += f"- **pH:** `{row[3] or 'N/A'}`\n"
                output += f"- **序列(前60):** `{row[2][:60]}...`\n---\n"
            else:
                output += f"### Top {i + 1} (ID: {result_id})\n"
                output += f"- **FAISS 距离:** `{dist:.4f}`\n"
                output += f"- **错误:** 数据库中未找到。\n---\n"

        return output

    except Exception as e:
        print(f"查询时发生错误: {e}", file=sys.stderr)
        return f"查询时发生错误: {e}"
    finally:
        if conn:
            DB_CONN_POOL.putconn(conn)


# --- 6. 启动 Gradio 接口 ---
if __name__ == "__main__":
    
    iface = gr.Interface(
        fn=handle_search_query,
        inputs=[
            gr.Textbox(lines=5, label="输入查询序列 (FASTA 格式或纯序列)", 
                       placeholder=">Query_Protein\nMSNYFVSGISSGIGNALARLLAARGDTVYGLGRKLLSFNNASIHYRQIDLSCLLDLEHQ..."),
            gr.Slider(minimum=1, maximum=20, value=5, step=1, label="返回 Top-N 结果")
        ],
        outputs=gr.Markdown(label="检索结果"),
        title="蛋白质序列 FAISS 检索系统",
        description="输入一个蛋白质序列，通过嵌入向量检索最相似的 Top-N 序列。",
        allow_flagging="never"
    )
    
    print("--- 正在启动 Gradio 服务 (http://127.0.0.1:7860) ---")
    iface.launch(server_name="0.0.0.0", server_port=7860)