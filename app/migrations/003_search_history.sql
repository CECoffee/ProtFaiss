-- Search History Migration
-- Run against protein_db after 001_auth_tables.sql
-- Before running: verify no duplicate non-null search_task_id values:
--   SELECT search_task_id, COUNT(*) FROM gpu_tasks
--   WHERE search_task_id IS NOT NULL
--   GROUP BY search_task_id HAVING COUNT(*) > 1;

ALTER TABLE gpu_tasks
    ADD CONSTRAINT uq_gpu_tasks_search_task_id UNIQUE (search_task_id);

CREATE TABLE search_history_hits (
    search_task_id  VARCHAR(64) NOT NULL
                    REFERENCES gpu_tasks(search_task_id) ON DELETE CASCADE,
    rank            INTEGER     NOT NULL,
    protein_row_id  INTEGER     NOT NULL,
    faiss_distance  REAL        NOT NULL,
    PRIMARY KEY (search_task_id, rank)
);

CREATE INDEX idx_search_hits_task ON search_history_hits (search_task_id, rank);
