from typing import Dict, List

DB_CONFIG: Dict[str, object] = {
    "host": "localhost",
    "port": 5432,
    "dbname": "protein_db",
    "user": "postgres",
    "password": "0909",
}

FAISS_SHARD_DIR = "indices/1m"
ESM2_MODEL_DIR = "models/esm2"

CORS_ORIGINS: List[str] = [
    "http://localhost:5173",   # Vite dev server
    "http://127.0.0.1:5173",
]

MAX_DB_CONNS = 20
MAX_CONCURRENT_ENCODINGS = 3
THREADPOOL_WORKERS = 32
FAISS_SEARCH_WORKERS = 8
