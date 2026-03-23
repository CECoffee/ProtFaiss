from typing import Dict, List

# Legacy fallback
# 实际连接参数由 app.core.db.get_db_config() 解析（config.yml 优先）。
DB_CONFIG: Dict[str, object] = {
    "host": "localhost",
    "port": 5432,
    "dbname": "protein_db",
    "user": "postgres",
    "password": "0909",
}

MAX_DB_CONNS = 20

ESM2_MODEL_DIR = "models/esm2"

CORS_ORIGINS: List[str] = [
    "http://localhost:5173",   # Vite dev server
    "http://127.0.0.1:5173",
]

# Dataset builder paths
DATASETS_ROOT = "datasets"

# Hot-reloadable runtime config (see config.yml)
CONFIG_YML_PATH = "config.yml"
