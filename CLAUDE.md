# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FaaIndex is a **protein sequence similarity search system** that encodes protein sequences using Facebook's ESM2 model (1280-dim embeddings) and retrieves similar proteins via FAISS vector search backed by PostgreSQL metadata.

## Running the Application

```bash
# Start both backend + frontend with one command
bash scripts/dev.sh

# Backend only (FastAPI, API-only, no static serving)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend only (Vue 3 + Vite dev server, http://localhost:5173)
cd frontend && npm run dev

# Gradio web UI (legacy)
python legacy/app_gradio.py

# Legacy monolithic backend
uvicorn legacy.app_backend:app --host 0.0.0.0 --port 8000
```

## Frontend (Vue 3)

```bash
# Install dependencies (first time)
cd frontend && npm install

# Development server (proxies /query/* and /health to localhost:8000)
npm run dev

# Production build (outputs to frontend/dist/)
npm run build
```

## Testing & Load Testing

```bash
# Stress test the async submit→poll API (adjust --concurrent as needed)
python tests/stress_test_api.py --concurrent 1000

# Stress test Gradio interface via SSE
python tests/stress_test_gradio.py
```

## Data Pipeline Tools

```bash
# Build GPU-accelerated IVF_PQ FAISS index from CSV
python tools/build_index_ivfpq.py

# Shard a FAISS index across multiple files
python tools/faiss_split.py

# Import FASTA protein sequences into PostgreSQL
python tools/insert_fasta_to_db.py
```

## Architecture

### Request Flow
1. Client POSTs sequence to `/query/submit` → receives `task_id`
2. Background worker calls `core/encoder.py` → ESM2 forward pass → 1280-dim vector
3. `search/retriever.py` searches all FAISS shards in parallel → top-k candidates
4. `search/db_queries.py` fetches protein metadata from PostgreSQL for matching IDs
5. Client polls `GET /query/result/{task_id}` until status is `done`

### Key Modules (`app/`)

```
app/
  main.py                    App factory, lifespan (model/shard/db init on startup)
  core/
    config.py                Shared constants: DB creds, ESM2 path, CORS, dataset paths
    db.py                    PostgreSQL connection pool (psycopg2)
    encoder.py               ESM2 model init + tokenize/embed logic
  search/
    config.py                Search concurrency limits, FAISS shard dir
    retriever.py             Loads FAISS shards, runs parallel shard searches
    tasks.py                 In-memory task store + ThreadPoolExecutor background pipeline
    routes.py                FastAPI route handlers (/query/submit, /query/result)
    db_queries.py            blocking_db_get_rows_from_table
  build/
    config.py                Index algorithm parameters (HNSW, IVF-PQ)
    registry_sync.py         Sync file-locked registry I/O (cross-process)
    dataset_registry.py      Async CRUD wrapper for registry.json
    index_builder.py         FASTA parsing, batch encoding, flat/ivfpq/hnsw build
    worker.py                Subprocess entry: python -m app.build.worker
    routes.py                /build/submit, /build/status, /datasets CRUD
    db_operations.py         blocking_create/insert/drop protein table
```

### Concurrency Constraints
- `MAX_CONCURRENT_ENCODINGS = 3` — semaphore limits simultaneous GPU forward passes
- `FAISS_SEARCH_WORKERS = 8` — parallel threads per query across shards
- `THREADPOOL_WORKERS = 32` — executor pool for all blocking operations
- Thread locks guard GPU state and FAISS index access

### Data Assets
- `models/esm2/` — ESM2 650M model weights (facebook/esm2_t33_650M_UR50D, ~2.6GB)
- `indices/1m/` — Sharded FAISS indices for 1M vectors
- `indices/10m/` — Sharded IVF_PQ indices for 10M vectors (in progress)
- `data/` — Sample data files (FASTA, CSV) and legacy flat FAISS indices
- `static_legacy/index.html` — Archived vanilla JS frontend (reference only)

### Database
PostgreSQL on `localhost:5432`, database `protein_db`. Main table `proteins_mock_1M` with columns: `id`, `original_header`, `sequence`, `ph_processed`, `ko_number`, `ec_number`.

## Environment

**Backend**: Dependencies managed via Conda (`freeze.yml`). Key packages: `torch==2.9.0+cu130`, `faiss-gpu==1.9.0`, `transformers==4.57.1`, `fastapi==0.115.0`, `uvicorn==0.38.0`.

**Frontend**: Node.js + npm. Key packages: `vue@3`, `vite@5`, `axios@1`. See `frontend/package.json`.

The legacy `legacy/app_backend.py` and `legacy/app_gradio.py` are standalone monolithic alternatives to the modular `app/` package — avoid mixing them.
