# ProtFaiss

蛋白质序列相似性搜索系统。使用 Facebook ESM2 模型将蛋白质序列编码为 1280 维向量，通过 FAISS 向量索引实现高效相似性检索，元数据存储于 PostgreSQL。支持多用户访问、JWT 鉴权、GPU 公平调度与 Vue 3 前端。

---

## 目录

- [系统架构](#系统架构)
  - [单节点模式（传统）](#单节点模式传统)
  - [集群模式（分布式）](#集群模式分布式)
- [搜索与构建流程](#搜索与构建流程)
- [部署](#部署)
  - [单节点快速开始](#单节点快速开始)
  - [集群模式（多机多卡）](#集群模式多机多卡-1)
  - [Kubernetes 部署](#kubernetes-部署)
- [目录结构](#目录结构)
- [配置参考](#配置参考)
- [工具与测试](#工具与测试)
- [技术栈](#技术栈)
- [环境变量](#环境变量)

---

## 系统架构

### 单节点模式（传统）

`config.yml` 中 `cluster.enabled: false`（默认）。所有 GPU 计算（ESM2 编码、FAISS 搜索、索引构建）在 Daemon 进程本地执行。

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

### 集群模式（分布式）

`config.yml` 中 `cluster.enabled: true`。Daemon 演变为**控制平面**，GPU 计算全部分发到远程 **Worker 节点**。适用于多机多卡算力集群（K8s/裸机）。

```
[前端 Vue3]
    │ HTTP :8000
[API Gateway — FastAPI，无状态]
    │ IPC (TCP 9812)
[控制平面 — app/daemon]
    │  RPC dispatch · RBAC · 调度器 · Worker 注册表 · Redis · PostgreSQL
    │
    │ ① Worker 注册/心跳/task_done  (Worker → CP, 9812)
    │ ② 任务分发                    (CP → Worker, 9820)
    │
    ├────────────────────────────────────┐
[Worker 节点 A :9820]          [Worker 节点 B :9820]
 ESM2 + FAISS + Build           ESM2 + FAISS + Build
 GPU 0,1                        GPU 0
 本地 VRAM LRU 缓存              本地 VRAM LRU 缓存

[共享存储 — NFS]
  /shared/datasets/   (FASTA、FAISS 索引、build_config.json)
  /shared/models/     (ESM2 模型权重，只读)

[Redis]
  任务状态存储（task:{id} → JSON，10 min TTL）
```

#### 通信协议

两条独立 TCP 通道，均使用相同的 **4 字节大端长度前缀 + UTF-8 JSON** 协议：

| 方向 | 端口 | 用途 |
|------|------|------|
| Worker → 控制平面 | 9812 | `worker.register` / `worker.heartbeat` / `worker.task_done` |
| 控制平面 → Worker | 9820 | `worker.search` / `worker.build` / `worker.unload` |

#### Dataset 亲和路由

调度器选择 Worker 时优先路由到**已将目标数据集加载进 VRAM** 的节点，避免冷启动延迟。心跳携带 `cached_datasets` 列表，控制平面实时维护亲和映射。

---

## 搜索与构建流程

### 搜索请求（集群模式）

```
1. 客户端 POST /query/submit (JWT)
2. API → 控制平面: search.submit RPC
3. 控制平面:
   a. 解析用户激活数据集
   b. 将任务参数写入 Redis (task:{id})
   c. 插入 gpu_tasks 记录 (status=pending)
4. 调度器（异步循环，500ms 间隔）:
   a. 亲和路由 → 选择最优 Worker
   b. 分配 ClusterGpuPool slot
   c. 发送 worker.search RPC 到 Worker
5. Worker:
   a. 按需加载 FAISS 分片到 GPU（LRU 缓存）
   b. ESM2 编码序列 → 1280 维向量
   c. 并行搜索 FAISS 分片
   d. 查询 PostgreSQL 元数据
   e. 结果写回 Redis
   f. 发送 worker.task_done → 控制平面释放 slot
6. 客户端轮询 GET /query/result/{task_id}
   → 控制平面从 Redis 读取返回
```

### 索引构建（集群模式）

```
1. 客户端上传 FASTA → API 保存到共享存储临时路径
2. 控制平面 build.submit:
   a. 创建 dataset 记录 (status=building)
   b. 写 build_config.json 到 NFS
   c. 插入 gpu_tasks (type=build)
3. 调度器选择 Worker，发送 worker.build RPC
4. Worker 执行完整构建流水线:
   导入 DB → ESM2 编码 → 构建 FAISS 索引 → 写入 NFS
   每步通过 DB 更新进度
5. 构建完成 → datasets.status = 'ready'
6. 客户端轮询 /build/status/{id} 跟踪进度
```

---

## 部署

### 单节点快速开始

#### 环境要求

- Conda（Python 环境）
- Node.js + npm（前端）
- PostgreSQL（例：`localhost:5432`，库 `protein_db`）
- CUDA 环境

#### 安装

```bash
# Python 环境
conda env create -f freeze.yml
conda activate protfaiss

# 前端依赖
cd frontend && npm install
```

#### 数据库初始化

```bash
psql -U postgres -d protein_db -f app/migrations/001_auth_tables.sql
```

#### 启动

```bash
# 一键启动（daemon + API + 前端）
bash scripts/dev.sh
```

或分别启动：

```bash
python -m app.daemon          # Daemon（先启动）
python -m app.api             # API
python -m app.cli             # 交互式 CLI（implicit admin）
cd frontend && npm run dev    # 前端 http://localhost:5173
```

首次启动时 Daemon 自动创建 admin 用户。若未设置 `ADMIN_PASSWORD`，密码将打印到控制台。

---

### 集群模式（多机多卡）

#### 前提条件

- 所有节点挂载同一 NFS 目录（`/shared/datasets`、`/shared/models`）
- Redis 实例（所有节点可达）
- PostgreSQL 实例（所有节点可达）
- ESM2 模型权重已放置到 `/shared/models/`

#### 安装（所有节点）

```bash
conda env create -f freeze.yml
conda activate protfaiss
```

#### 数据库迁移

```bash
# 任一节点执行（仅一次）
psql -U postgres -d protein_db -f app/migrations/001_auth_tables.sql
psql -U postgres -d protein_db -f app/migrations/002_cluster_tables.sql
```

#### config.yml 关键配置

```yaml
cluster:
  enabled: true
  control_plane_host: "<控制平面节点 IP>"   # Worker 连接此地址注册
  control_plane_port: 9812

redis:
  host: "<Redis IP>"
  port: 6379

storage:
  datasets_root: "/shared/datasets"
  models_root: "/shared/models"

daemon:
  ipc_host: "0.0.0.0"   # 控制平面需要接受来自 Worker 的连接

worker:
  host: "0.0.0.0"
  port: 9820
  node_id: ""            # 留空自动使用 hostname
```

#### 启动顺序

```bash
# 步骤 1：控制平面节点（无需 GPU）
python -m app.daemon &    # 控制平面 IPC :9812
python -m app.api &       # HTTP API :8000

# 步骤 2：各 GPU Worker 节点（分别在每台机器上执行）
# 确保 config.yml 中 cluster.control_plane_host 指向控制平面 IP
python -m app.worker

# 步骤 3：前端（可选）
cd frontend && npm run build   # 生产构建
# 或
cd frontend && npm run dev     # 开发服务器 :5173
```

Worker 启动后会自动向控制平面注册，控制平面随即建立反向连接用于任务分发。

#### 验证

```bash
# CLI 连接控制平面查看集群状态
python -m app.cli
> system health          # 系统健康状态
> gpu queue             # 当前任务队列
```

---

### Kubernetes 部署

`k8s/` 目录包含完整部署清单：

```
k8s/
  nfs-pv.yaml          — NFS PersistentVolume + PVC（datasets + models）
  redis.yaml           — Redis StatefulSet + Service
  configmap.yaml       — config.yml ConfigMap + Secrets 模板
  control-plane.yaml   — Daemon + API Deployment + Service
  worker.yaml          — GPU Worker Deployment（含反亲和确保跨节点）
```

#### 部署步骤

```bash
# 1. 修改 NFS 服务器地址
vim k8s/nfs-pv.yaml    # 替换 nfs.server: "192.168.1.100"

# 2. 修改 Secrets（admin 密码、JWT 密钥）
vim k8s/configmap.yaml

# 3. 构建并推送镜像
docker build -f docker/Dockerfile.control-plane -t protfaiss-control-plane:latest .
docker build -f docker/Dockerfile.worker -t protfaiss-worker:latest .
# docker push ... （推送到你的 registry）

# 4. 按顺序部署
kubectl apply -f k8s/nfs-pv.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/control-plane.yaml
kubectl apply -f k8s/worker.yaml

# 5. 验证
kubectl get pods
kubectl logs -f deployment/protfaiss-control-plane -c daemon
kubectl logs -f deployment/protfaiss-worker
```

#### 扩缩容

```bash
# 增加 Worker 节点数（每个 Pod 独占一张 GPU，反亲和确保跨节点分布）
kubectl scale deployment protfaiss-worker --replicas=4

# 控制平面保持单副本（状态由 PostgreSQL + Redis 承载）
```

---

## 目录结构

```
app/
  daemon/                — 控制平面 IPC 服务进程
    operations/          — auth / build / config / dataset / gpu / search / user / worker
    worker_client.py     — 控制平面→Worker 的 TCP 客户端
  api/                   — FastAPI HTTP 层
    routes/              — auth, build, datasets, gpu, health, search, users, export_import
  cli/                   — 交互式 REPL（implicit admin）
    commands/            — build, config, datasets, gpu, search, system, users, export_import
  worker/                — GPU Worker 节点（集群模式）
    __main__.py          — Worker 入口：init ESM2 + 注册 + 心跳
    service.py           — 任务执行（search/build/unload）
    heartbeat.py         — 定期心跳发送
    vram_manager.py      — 本地 VRAM 释放计时器
  core/                  — 共享：config, DB pool, ESM2 encoder, GPU utils, Redis client
  auth/                  — 共享：JWT, 密码哈希, 用户 DB 操作
  search/                — 共享：FAISS retriever, 任务存储（Redis）, VRAM 计时器
  build/                 — 共享：索引构建器, dataset DB, export/import
  scheduler/             — 共享：GPU pool, 公平调度器, Worker 注册表, 亲和路由
    scheduler.py         — 双模调度：legacy（本地）+ cluster（远程分发）
    worker_registry.py   — Worker 注册表 + 心跳存活检测
    cluster_pool.py      — 集群 GPU slot 追踪（ClusterGpuPool）
    affinity.py          — Dataset 亲和路由
    fair_share.py        — 公平份额调度
    gpu_pool.py          — 单节点 GPU pool（legacy 模式）
  migrations/
    001_auth_tables.sql  — 基础表：users, datasets, gpu_tasks 等
    002_cluster_tables.sql — 集群表：cluster_workers, worker_dataset_cache

frontend/src/
  views/                 — SearchView, BuilderView, DatasetsView, GpuDashboard, admin/
  stores/                — Pinia stores (auth, gpu, theme)
  api/                   — Axios 客户端 + API 模块
  composables/           — usePolling, useBuildPolling, useDatasets
  i18n/                  — 中英文国际化

docker/
  Dockerfile.control-plane  — 控制平面镜像（无 GPU 依赖）
  Dockerfile.worker         — Worker 镜像（含 CUDA + FAISS-GPU）

k8s/                     — Kubernetes 部署清单
tools/                   — 独立工具脚本
tests/                   — 压力测试
scripts/                 — 开发启动脚本
```

---

## 配置参考

`config.yml` 支持运行时热重载（`POST /admin/reload-config`）。

| 节 | 说明 |
|---|---|
| `gpu` | 多 GPU 开关、编码设备、FAISS 设备、VRAM 限制、FP16 LUT |
| `search` | FAISS workers、并发编码数、线程池、nprobe、VRAM 闲时释放 |
| `build` | 编码批大小、IVF-PQ / HNSW 参数 |
| `scheduler` | GPU 槽位、用户配额、轮询间隔、超时、衰减因子、优先级、最大缓存数 |
| `daemon` | IPC host/port（集群模式需设为 `0.0.0.0`） |
| `api` | HTTP host/port、IPC 连接池大小 |
| `redis` | host / port / db / password |
| `storage` | `datasets_root`、`models_root`（集群模式指向 NFS 路径） |
| `cluster` | `enabled`、控制平面地址、心跳间隔/超时、task TTL |
| `worker` | Worker 监听地址、port、node_id |

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

## 技术栈

**后端**
- Python 3.x，PyTorch 2.9.0+cu130，FAISS-GPU 1.9.0
- Transformers 4.57.1（ESM2），FastAPI 0.115.0，Uvicorn
- psycopg2，python-jose（JWT），bcrypt，prompt-toolkit
- redis，py7zr

**前端**
- Vue 3，Vite 5，Naive UI，Pinia，Axios

**存储**
- PostgreSQL（`protein_db`）— 元数据、用户、任务队列
- Redis — 任务状态（集群模式）
- NFS / 本地文件系统 — FASTA、FAISS 索引、模型权重

---

## 环境变量

| 变量 | 说明 |
|---|---|
| `ADMIN_USERNAME` | 首次启动时创建的 admin 用户名（默认 `admin`） |
| `ADMIN_PASSWORD` | 首次启动时创建的 admin 密码（未设置则自动生成并打印） |
