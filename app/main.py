from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router as api_router
from .encoder import init_model
from .retriever import load_shards, FAISS_SHARDS
from .db import init_db_pool, close_db_pool
from .config import FAISS_SHARD_DIR, ESM2_MODEL_DIR, CORS_ORIGINS

app = FastAPI(title="Protein Search")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)

@app.on_event("startup")
def startup():
    print("startup: init model, load shards, init db pool ...")
    init_model(ESM2_MODEL_DIR)
    load_shards(FAISS_SHARD_DIR)
    init_db_pool()
    print("startup done: shards:", len(FAISS_SHARDS))

@app.on_event("shutdown")
def shutdown():
    print("shutdown: closing resources ...")
    close_db_pool()

# uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
