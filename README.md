# ProtFaiss

蛋白质序列相似性搜索系统。使用 Facebook ESM2 模型将蛋白质序列编码为 1280 维向量，通过 FAISS 向量索引实现高效相似性检索，元数据存储于 PostgreSQL。支持多用户访问、JWT 鉴权、GPU 公平调度与 Vue 3 前端。

---

## 架构

三进程设计，通过 TCP IPC 通信：

```
┌─────────────┐     IPC (TCP 9812)      ┌──────────────────────────────┐
│  app/api    │ ──────────────────────▶ │         app/daemon           │
│  FastAPI    │                         │  ESM2 · FAISS · DB · Sched   │
│  :8000      │                         └──────────────────────────────┘
└─────────────┘                                      ▲
                                                     │ IPC (TCP 9812)
┌─────────────┐                                      │
│  app/cli    │ ────────────────────────────────────▶│
│  REPL       │  (implicit admin, no JWT)
└─────────────┘
```

- **Daemon** — 长驻进程，独占 ESM2 模型、FAISS 分片缓存、PostgreSQL 连接池、GPU 调度器
- **API** — 轻量 FastAPI 层，本地验证 JWT 后通过 IPC 转发所有业务逻辑
- **CLI** — `psql` 风格交互式 REPL，以隐式 admin 身份直连 Daemon（无需 JWT）

---

## 快速开始

### 环境要求

- Conda（用于 Python 环境）
- Node.js + npm（用于前端）
- PostgreSQL（`localhost:5432`，数据库 `protein_db`）
- CUDA 13.0 兼容 GPU（推荐）

### 安装

```bash
# 创建 Python 环境
conda env create -f freeze.yml
conda activate protfaiss

# 安装前端依赖
cd frontend && npm install
```

### 数据库初始化

```bash
# 执行 SQL schema
psql -U postgres -d protein_db -f app/migrations/001_auth_tables.sql
```

### 启动

```bash
# 一键启动所有进程（daemon + API + 前端）
bash scripts/dev.sh
```

或分别启动：

```bash
python -m app.daemon          # Daemon（先启动）
python -m app.api             # API（需要 Daemon 运行）
python -m app.cli             # 交互式 CLI（需要 Daemon 运行）
cd frontend && npm run dev    # 前端开发服务器 http://localhost:5173
```

首次启动时，Daemon 会自动创建 admin 用户。若未设置 `ADMIN_PASSWORD` 环境变量，密码将打印到控制台。

---

## 搜索流程

1. 客户端 POST 序列到 `/query/submit`（需 JWT）→ 获得 `task_id`
2. API 将 `search.submit` RPC 转发给 Daemon
3. `GpuScheduler` 入队，按用户 `decayed_gpu_seconds` 计算公平优先级
4. Worker 调用 `core/encoder.py` → ESM2 前向传播 → 1280 维向量
5. `search/retriever.py` 并行搜索 FAISS 分片 → top-k 候选
6. `search/db_queries.py` 从 PostgreSQL 获取蛋白质元数据
7. 客户端轮询 `GET /query/result/{task_id}` 直到 `status == "done"`

---

## 目录结构

```
app/
  daemon/          — 长驻 IPC 服务进程
    operations/    — auth / build / config / dataset / gpu / search / user
  api/             — FastAPI HTTP 层
    routes/        — auth, build, datasets, gpu, health, search, users
  cli/             — 交互式 REPL
    commands/      — build, config, datasets, gpu, search, system, users
  core/            — 共享：config, DB pool, ESM2 encoder, GPU utils
  auth/            — 共享：JWT, 密码哈希, 用户 DB 操作
  search/          — 共享：FAISS retriever, 任务存储, VRAM 计时器
  build/           — 共享：索引构建器, dataset DB, worker 子进程
  scheduler/       — 共享：GPU pool, 公平调度器
  migrations/      — SQL schema + 迁移脚本

frontend/src/
  views/           — SearchView, BuilderView, DatasetsView, GpuDashboard, admin/
  stores/          — Pinia stores (auth, gpu, theme)
  api/             — Axios 客户端 + API 模块
  composables/     — usePolling, useBuildPolling, useDatasets
  i18n/            — 中英文国际化

tools/             — 独立工具脚本
tests/             — 压力测试、配置测试
scripts/           — 开发启动脚本
```

---

## 工具与测试

```bash
# API 压力测试（1000 并发）
python tests/stress_test_api.py --concurrent 1000

# 从 CSV 构建 GPU 加速 IVF_PQ FAISS 索引
python tools/build_index_ivfpq.py

# 将 FASTA 序列导入 PostgreSQL
python tools/insert_fasta_to_db.py

# 一次性迁移：registry.json → datasets 数据库表
python -m app.migrations.migrate_registry
```

---

## 配置

运行时配置文件 `config.yml`，支持热重载（`POST /admin/reload-config`）。

| 节 | 说明 |
|---|---|
| `gpu` | 多 GPU、编码设备、FAISS 设备、VRAM 限制、FP16 LUT |
| `search` | FAISS workers、并发编码数、线程池大小、nprobe |
| `build` | 编码批大小、IVF-PQ/HNSW 参数 |
| `scheduler` | GPU 槽位、配额、轮询间隔、超时、衰减因子、优先级 |
| `daemon` | IPC host/port（默认 `127.0.0.1:9812`） |
| `api` | HTTP host/port（默认 `:8000`）、IPC 连接池大小 |

---

## 技术栈

**后端**
- Python 3.x，PyTorch 2.9.0+cu130，FAISS-GPU 1.9.0
- Transformers 4.57.1（ESM2），FastAPI 0.121.1，Uvicorn
- psycopg2，python-jose（JWT），bcrypt，prompt-toolkit

**前端**
- Vue 3，Vite 5，Naive UI，Pinia，Axios

**数据库**
- PostgreSQL（`protein_db`）

---

## 环境变量

| 变量 | 说明 |
|---|---|
| `ADMIN_USERNAME` | 首次启动时创建的 admin 用户名（默认 `admin`） |
| `ADMIN_PASSWORD` | 首次启动时创建的 admin 密码（未设置则自动生成并打印） |
