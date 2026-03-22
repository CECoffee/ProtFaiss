-- ProtFaiss Multi-User Schema Migration
-- Run against protein_db

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. users
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(64)  NOT NULL UNIQUE,
    email         VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(16)  NOT NULL DEFAULT 'user'
                  CHECK (role IN ('user', 'admin')),
    gpu_quota     INTEGER      NOT NULL DEFAULT 1
                  CHECK (gpu_quota >= 0),
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);

-- ============================================================
-- 2. refresh_tokens
-- ============================================================
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ  NOT NULL,
    revoked    BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens (token_hash);

-- ============================================================
-- 3. datasets  (replaces registry.json)
-- ============================================================
CREATE TABLE IF NOT EXISTS datasets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    algorithm       VARCHAR(16)  NOT NULL CHECK (algorithm IN ('flat', 'ivfpq', 'hnsw')),
    status          VARCHAR(16)  NOT NULL DEFAULT 'building'
                    CHECK (status IN ('building', 'ready', 'error')),
    visibility      VARCHAR(16)  NOT NULL DEFAULT 'private'
                    CHECK (visibility IN ('private', 'public')),
    error_msg       TEXT,
    fasta_path      TEXT,
    index_dir       TEXT,
    db_table        VARCHAR(128),
    num_sequences   INTEGER      NOT NULL DEFAULT 0,
    num_indexed     INTEGER      NOT NULL DEFAULT 0,
    progress_step   VARCHAR(32)  NOT NULL DEFAULT 'idle',
    progress_pct    REAL         NOT NULL DEFAULT 0,
    progress_detail TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_datasets_owner      ON datasets (owner_id);
CREATE INDEX IF NOT EXISTS idx_datasets_status     ON datasets (status);
CREATE INDEX IF NOT EXISTS idx_datasets_visibility ON datasets (visibility);

-- ============================================================
-- 4. user_active_datasets  (per-user active dataset pointer)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_active_datasets (
    user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE
);

-- ============================================================
-- 5. gpu_tasks  (unified GPU task queue: build + search)
-- ============================================================
CREATE TABLE IF NOT EXISTS gpu_tasks (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_type      VARCHAR(16)  NOT NULL CHECK (task_type IN ('build', 'search')),
    status         VARCHAR(16)  NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
    -- lower number = higher priority
    priority       INTEGER      NOT NULL DEFAULT 100,
    dataset_id     UUID         REFERENCES datasets(id) ON DELETE SET NULL,
    search_task_id VARCHAR(64),
    gpu_slots      INTEGER      NOT NULL DEFAULT 1,
    submitted_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ,
    gpu_seconds    REAL         NOT NULL DEFAULT 0,
    pid            INTEGER,
    error_msg      TEXT
);

CREATE INDEX IF NOT EXISTS idx_gpu_tasks_status ON gpu_tasks (status, priority, submitted_at);
CREATE INDEX IF NOT EXISTS idx_gpu_tasks_user   ON gpu_tasks (user_id, status);

-- ============================================================
-- 6. user_gpu_usage  (fair-share accounting)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_gpu_usage (
    user_id             UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    total_gpu_seconds   REAL NOT NULL DEFAULT 0,
    decayed_gpu_seconds REAL NOT NULL DEFAULT 0,
    last_decay_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
