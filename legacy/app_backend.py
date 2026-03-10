import os
import re
import sys
import threading
import time
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict, Any

import faiss
import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
import psycopg2.pool
from transformers import AutoTokenizer, EsmModel

# ---------- 配置 ----------
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "protein_db",
    "user": "postgres",
    "password": "0909",
}
FAISS_SHARD_DIR = "src/faiss_shards"
MAX_DB_CONNS = 20
MAX_CONCURRENT_ENCODINGS = 3
THREADPOOL_WORKERS = 32
FAISS_SEARCH_WORKERS = 8

# ---------- 全局资源 ----------
FAISS_SHARDS: List[faiss.Index] = []
FAISS_SHARD_LOCKS: List[threading.Lock] = []
ESM2_TOKENIZER = None
ESM2_MODEL = None
DB_CONN_POOL = None

ENCODE_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_ENCODINGS)
BLOCKING_EXECUTOR = ThreadPoolExecutor(max_workers=THREADPOOL_WORKERS)

# ---------- 任务存储（单机内存示例） ----------
# task_store: task_id -> {"tid": ..., "status": "pending|done|error", "result": ..., "error": ...}
task_store: Dict[str, Dict[str, Any]] = {}
task_store_lock = asyncio.Lock()

# ---------- App ----------
app = FastAPI(title="Protein Search")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- 请求模型 ----------
class SearchRequest(BaseModel):
    sequence: str
    top_k: int = 5
    pooling: str = "mean"

class SubmitResponse(BaseModel):
    task_id: str

# ---------- 启动加载（略，复用之前 startup 内容） ----------
@app.on_event("startup")
def startup():
    global FAISS_SHARDS, ESM2_TOKENIZER, ESM2_MODEL, DB_CONN_POOL, GPU_RESOURCES

    print("startup: load shards, model, db pool ...")

    # -- load shards
    shard_paths = sorted([
        os.path.join(FAISS_SHARD_DIR, f)
        for f in os.listdir(FAISS_SHARD_DIR)
        if f.endswith(".faiss")
    ])
    if not shard_paths:
        raise RuntimeError("No faiss shards found")

    # 统一 GPU 资源池（只创建一次）
    GPU_RESOURCES = faiss.StandardGpuResources()

    for i, p in enumerate(shard_paths):
        idx_cpu = faiss.read_index(p)
        if torch.cuda.is_available():
            idx_gpu = faiss.index_cpu_to_gpu(GPU_RESOURCES, i % torch.cuda.device_count(), idx_cpu)
            idx_gpu.nprobe = 8  # 可调整
            FAISS_SHARDS.append(idx_gpu)
        else:
            FAISS_SHARDS.append(idx_cpu)
        FAISS_SHARD_LOCKS.append(threading.Lock())

    # -- load model
    model_dir = "src/esm2_model"

    ESM2_TOKENIZER = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    ESM2_MODEL = EsmModel.from_pretrained(model_dir, local_files_only=True)
    if torch.cuda.is_available():
        ESM2_MODEL.cuda()

    # -- db pool
    DB_CONN_POOL = psycopg2.pool.ThreadedConnectionPool(1, MAX_DB_CONNS, **DB_CONFIG)

# ---------- 辅助阻塞函数（和旧版相同） ----------
def blocking_encode(sequence_str: str, pooling: str = "mean"):
    inputs = ESM2_TOKENIZER(sequence_str, return_tensors="pt", max_length=2048, truncation=True)
    with torch.no_grad():
        input_ids = inputs["input_ids"]
        attention_mask = inputs["attention_mask"]
        if torch.cuda.is_available():
            input_ids = input_ids.cuda()
            attention_mask = attention_mask.cuda()
        outputs = ESM2_MODEL(input_ids=input_ids, attention_mask=attention_mask)
        features = outputs.last_hidden_state
        masked_features = features * attention_mask.unsqueeze(2)
        sum_features = torch.sum(masked_features, dim=1)
        if pooling == 'mean':
            pooled = sum_features / attention_mask.sum(dim=1, keepdim=True)
        elif pooling == 'max':
            pooled, _ = torch.max(masked_features, dim=1)
        elif pooling == 'sum':
            pooled = sum_features
        else:
            pooled = sum_features / attention_mask.sum(dim=1, keepdim=True)
        return pooled.detach().contiguous()

def _search_one_shard(index, query_vector, top_k, shard_idx=None):
    try:
        lock = FAISS_SHARD_LOCKS[shard_idx]
        with lock:
            D, I = index.search(query_vector, top_k)
        return D[0].tolist(), I[0].tolist()
    except Exception as e:
        print("Shard error:", e)
        return [], []

def blocking_faiss_search(query_vector: torch.Tensor, top_k: int):
    """搜索 GPU 版 FAISS 索引（支持 torch.Tensor 输入）"""
    if isinstance(query_vector, torch.Tensor):
        if query_vector.is_cuda:
            # pinned memory + async copy
            query_cpu = query_vector.detach().cpu().pin_memory()
        else:
            query_cpu = query_vector.detach()
        query_np = np.asarray(query_cpu, dtype=np.float32)
    else:
        query_np = query_vector.astype('float32', copy=False)

    results = []
    # 多 GPU shard 并发搜索
    with ThreadPoolExecutor(max_workers=min(FAISS_SEARCH_WORKERS, len(FAISS_SHARDS))) as ex:
        futures = [ex.submit(_search_one_shard, idx, query_np, top_k, si) for si, idx in enumerate(FAISS_SHARDS)]
        for fut in as_completed(futures):
            D, I = fut.result()
            if D and I:
                for d, i in zip(D, I):
                    if int(i) >= 0:
                        results.append((float(d), int(i)))

    return sorted(results, key=lambda x: x[0])[:top_k]


def blocking_db_get_rows(ids: List[int]):
    conn = None
    try:
        conn = DB_CONN_POOL.getconn()
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(ids))
        cur.execute(f"""
            SELECT id, original_header, sequence, ph_processed, ko_number, ec_number
            FROM "proteins_mock_1M"
            WHERE id IN ({placeholders})
        """, tuple(ids))
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        if conn:
            DB_CONN_POOL.putconn(conn)

# ---------- 异步提交 + 获取结果（用于长任务或非阻塞返回） ----------
@app.post("/query/submit", response_model=SubmitResponse)
async def submit(req: SearchRequest):
    """提交异步任务，返回 task_id。后台会把结果写入 task_store[task_id]"""

    task_id = str(uuid.uuid4())
    # 初始化 task 状态（pending）
    async with task_store_lock:
        task_store[task_id] = {"status": "pending", "result": None, "error": None, "created_at": time.time()}

    # 后台调度任务（不阻塞请求）
    asyncio.create_task(_background_task(task_id, req.sequence, req.top_k, req.pooling))
    return {"task_id": task_id}

async def _background_task(task_id: str, sequence: str, top_k: int, pooling: str):
    loop = asyncio.get_event_loop()
    try:
        # 1) 清理 & encode (受 semaphore)
        cleaned = re.sub(r"^>.*\n", "", sequence, flags=re.MULTILINE)
        cleaned = re.sub(r"\s", "", cleaned).upper()
        if not cleaned:
            raise ValueError("sequence empty after cleaning")

        start_time = time.time()
        async with ENCODE_SEMAPHORE:
            qvec = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_encode, cleaned, pooling)
        esm_time = time.time()

        # 2) faiss
        merged = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_faiss_search, qvec, top_k)
        ids = [r[1] for r in merged]
        faiss_time = time.time()

        # 3) db
        rows = []
        if ids:
            rows = await loop.run_in_executor(BLOCKING_EXECUTOR, blocking_db_get_rows, ids)
        db_time = time.time()

        rows_map = {row[0]: row for row in rows}
        out = []
        for dist, rid in merged:
            row = rows_map.get(rid)
            if row:
                out.append({
                    "id": int(row[0]),
                    "header": row[1],
                    "sequence": row[2],
                    "ph": row[3],
                    "ko": row[4],
                    "ec": row[5],
                    "faiss_distance": float(dist)
                })
            else:
                out.append({"id": rid, "faiss_distance": float(dist), "note": "db miss"})

        async with task_store_lock:
            task_store[task_id].update({
                "status": "done",
                "result": out,
                "times": [{
                    "total_time": db_time - start_time,
                    "esm_time": esm_time - start_time,
                    "faiss_time": faiss_time - esm_time,
                    "db_time": db_time - faiss_time
                }]
            })
    except Exception as e:
        async with task_store_lock:
            task_store[task_id]["status"] = "error"
            task_store[task_id]["error"] = str(e)
        print("background task error:", e, file=sys.stderr)

@app.get("/query/result/{task_id}")
async def get_result(task_id: str):
    async with task_store_lock:
        task = task_store.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")\
        # 返回安全副本
        return {
            "task_id": task_id,
            "status": task["status"],
            "result": task.get("result"),
            "times": task.get("times"),
            "error": task.get("error")
        }

# ---------- health ----------
@app.get("/health")
async def health():
    return {"status": "ok", "shards": len(FAISS_SHARDS)}


from fastapi.staticfiles import StaticFiles
if os.path.isdir("src/app"):
    static_files = StaticFiles(directory="src/app")
    app.mount("/", static_files, name="frontend")

# uvicorn app_backend:app --host 0.0.0.0 --port 8000