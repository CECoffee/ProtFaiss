# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FaaIndex is a **protein sequence similarity search system** that encodes protein sequences using Facebook's ESM2 model (1280-dim embeddings) and retrieves similar proteins via FAISS vector search backed by PostgreSQL metadata. It supports multi-user access with JWT auth, GPU scheduling, and a Vue 3 frontend.

## Running the Application

```bash
# Start both backend + frontend
bash scripts/dev.sh

# Backend only (FastAPI)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend only (http://localhost:5173, proxies /query/*, /auth/*, /build/*, /gpu/*, /admin/* to :8000)
cd frontend && npm run dev

# Production frontend build (outputs to frontend/dist/)
cd frontend && npm build
```

## Testing & Tools

```bash
# Stress test the async submit→poll API
python tests/stress_test_api.py --concurrent 1000

# Build GPU-accelerated IVF_PQ FAISS index from CSV
python tools/build_index_ivfpq.py

# Import FASTA sequences into PostgreSQL
python tools/insert_fasta_to_db.py

# One-time migration: registry.json → datasets DB table
python -m app.migrations.migrate_registry
```

## Architecture

### Request Flow (Search)
1. Client POSTs sequence to `/query/submit` (JWT required) → receives `task_id`
2. `GpuScheduler` enqueues task; fair-share priority assigned based on user's `decayed_gpu_seconds`
3. Background worker calls `core/encoder.py` → ESM2 forward pass → 1280-dim vector
4. `search/retriever.py` searches FAISS shards in parallel → top-k candidates
5. `search/db_queries.py` fetches protein metadata from PostgreSQL
6. Client polls `GET /query/result/{task_id}` until `status == "done"`

### Backend Modules (`app/`)

```
main.py                    — App factory, lifespan: DB pool, model load, scheduler start
auth/                      — JWT auth (access 30min + refresh 7d stored hashed in DB)
  routes.py                — /auth/register, /auth/login, /auth/refresh, /auth/logout, /auth/me
  dependencies.py          — get_current_user, require_admin, get_optional_user (FastAPI deps)
  init_admin.py            — run_migration() + ensure_admin() at startup
scheduler/
  scheduler.py             — GpuScheduler: asyncio loop (0.5s), fair-share backfill allocation
  gpu_pool.py              — In-memory GPU slot tracking
  fair_share.py            — Decayed usage penalty; search (priority 10) preempts build (priority 100)
  routes.py                — /gpu/queue, /admin/gpu/queue, /admin/gpu/tasks/{id}/cancel
core/
  encoder.py               — ESM2 model init + blocking_encode(); idle VRAM release logic
  config_loader.py         — Hot-reload YAML config (config.yml)
  db.py                    — psycopg2 connection pool
search/
  retriever.py             — LRU multi-dataset FAISS cache (OrderedDict), blocking_faiss_search()
  tasks.py                 — In-memory task store + ThreadPoolExecutor pipeline, user_id tracking
  routes.py                — /query/submit, /query/result/{id}
build/
  dataset_db.py            — PostgreSQL CRUD for datasets + user_active_datasets (replaced registry.json)
  index_builder.py         — FASTA parsing, batch encode, flat/ivfpq/hnsw index build
  worker.py                — Subprocess entry: python -m app.build.worker (writes progress to DB)
  routes.py                — /build/submit, /build/status/{id}, /datasets CRUD
users/
  routes.py                — /admin/users CRUD, /admin/stats
migrations/
  001_auth_tables.sql      — users, refresh_tokens, datasets, user_active_datasets, gpu_tasks, user_gpu_usage
```

### Concurrency
- `MAX_CONCURRENT_ENCODINGS` — semaphore limits simultaneous GPU forward passes (config.yml)
- `FAISS_SEARCH_WORKERS` — parallel threads per query across shards
- `THREADPOOL_WORKERS` — executor pool for all blocking operations
- Thread locks guard GPU state and FAISS index access

### Frontend (`frontend/src/`)

Vue 3 + Vite + Naive UI + Pinia. All routes require auth except `/login`.

```
main.js                    — createApp, Pinia, Naive UI, router
router/index.js            — Guards: requiresAuth (→/login), requiresAdmin (→/search)
stores/auth.js             — user, tokens, login/logout, fetchMe
stores/gpu.js              — GPU queue polling
api/client.js              — axios instance: JWT auto-attach + silent 401→refresh→retry
api/auth.js, buildApi.js, proteinSearch.js, adminApi.js
layouts/AppLayout.vue      — Sidebar + topbar (Naive UI NLayout)
views/SearchView.vue       — Sequence input → submit → poll → results
views/BuilderView.vue      — FASTA upload → index build → progress polling
views/DatasetsView.vue     — Dataset CRUD + active dataset switcher
views/GpuDashboard.vue     — Live GPU queue view
views/admin/               — UsersView.vue (CRUD), SystemView.vue (config/stats)
composables/usePolling.js  — Generic interval-based task polling
composables/useBuildPolling.js — Build-specific polling with stage tracking
```

### Database
PostgreSQL `localhost:5432`, database `protein_db`.
- `users` — id, username, email, password_hash, role, gpu_quota, is_active
- `datasets` — owner_id, name, algorithm, status, visibility, fasta_path, index_dir, db_table
- `user_active_datasets` — per-user active dataset mapping
- `gpu_tasks` — unified build + search task queue for fair-share accounting
- `user_gpu_usage` — decayed_gpu_seconds per user

### Config (`config.yml`)
Hot-reloaded at runtime. Key sections: `gpu` (devices, fp16, VRAM), `search` (workers, nprobe), `build` (batch sizes, IVF-PQ/HNSW params), `scheduler` (slots, quotas, timeouts, decay, priorities, `max_cached_datasets`).

## Environment

**Backend**: Conda (`freeze.yml`). Key: `torch==2.9.0+cu130`, `faiss-gpu==1.9.0`, `transformers==4.57.1`, `fastapi==0.115.0`.

**Frontend**: Node.js + npm. Key: `vue@3`, `vite@5`, `naive-ui`, `pinia`, `axios@1`.

**First run**: Admin user auto-created on startup — check console for credentials if `ADMIN_PASSWORD` env var is not set.

The `legacy/` directory contains standalone monolithic alternatives — do not mix with `app/`.
