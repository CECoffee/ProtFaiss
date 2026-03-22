-- Migration 002: Cluster tables for distributed worker architecture
-- Run after 001_auth_tables.sql

-- Worker registry: tracks registered GPU worker nodes
CREATE TABLE IF NOT EXISTS cluster_workers (
    node_id        TEXT PRIMARY KEY,
    address        TEXT NOT NULL,            -- "host:port" for WorkerClient connections
    gpu_count      INTEGER NOT NULL DEFAULT 0,
    gpu_slots      INTEGER NOT NULL DEFAULT 0,
    capabilities   TEXT[] NOT NULL DEFAULT '{}',  -- ['encode', 'search', 'build']
    status         TEXT NOT NULL DEFAULT 'online', -- online | draining | offline
    last_heartbeat TIMESTAMPTZ,
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata       JSONB DEFAULT '{}'
);

-- Dataset-to-worker cache affinity: which datasets are loaded in which workers' VRAM
CREATE TABLE IF NOT EXISTS worker_dataset_cache (
    node_id     TEXT REFERENCES cluster_workers(node_id) ON DELETE CASCADE,
    dataset_id  UUID REFERENCES datasets(id) ON DELETE CASCADE,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node_id, dataset_id)
);

-- Extend gpu_tasks with worker assignment fields
ALTER TABLE gpu_tasks
    ADD COLUMN IF NOT EXISTS assigned_worker TEXT REFERENCES cluster_workers(node_id),
    ADD COLUMN IF NOT EXISTS assignment_epoch INTEGER DEFAULT 0;

-- Index for fast lookup of tasks assigned to a specific worker
CREATE INDEX IF NOT EXISTS idx_gpu_tasks_assigned_worker
    ON gpu_tasks (assigned_worker)
    WHERE status = 'running';
