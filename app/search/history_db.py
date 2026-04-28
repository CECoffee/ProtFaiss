import logging
from typing import List

from app.core.db import get_pool

logger = logging.getLogger(__name__)


def blocking_save_search_hits(search_task_id: str, hits: list) -> None:
    """Persist search result hits to search_history_hits. Failure is logged but never raised."""
    if not hits:
        return
    pool = get_pool()
    conn = None
    try:
        conn = pool.getconn()
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO search_history_hits (search_task_id, rank, protein_row_id, faiss_distance)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                (search_task_id, rank, hit["id"], hit["faiss_distance"])
                for rank, hit in enumerate(hits, 1)
            ],
        )
        conn.commit()
        cur.close()
    except Exception:
        logger.exception("Failed to persist search hits for task %s", search_task_id)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            pool.putconn(conn)


def blocking_get_search_history(
    user_id: str, role: str, limit: int = 20, offset: int = 0
) -> dict:
    """Return paginated list of past search tasks with hit counts."""
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    pool = get_pool()
    conn = None
    try:
        conn = pool.getconn()
        cur = conn.cursor()

        user_filter = "" if role == "admin" else "AND gt.user_id = %s"
        params_filter: list = [] if role == "admin" else [user_id]

        cur.execute(
            f"""
            SELECT
                gt.search_task_id,
                gt.user_id,
                u.username,
                gt.dataset_id,
                d.name  AS dataset_name,
                gt.submitted_at,
                gt.completed_at,
                gt.gpu_seconds,
                COUNT(sh.rank) AS hit_count
            FROM gpu_tasks gt
            LEFT JOIN users u ON u.id = gt.user_id
            LEFT JOIN datasets d ON d.id = gt.dataset_id
            LEFT JOIN search_history_hits sh ON sh.search_task_id = gt.search_task_id
            WHERE gt.task_type = 'search'
              AND gt.status = 'done'
              AND gt.search_task_id IS NOT NULL
              {user_filter}
            GROUP BY gt.search_task_id, gt.user_id, u.username, gt.dataset_id,
                     d.name, gt.submitted_at, gt.completed_at, gt.gpu_seconds
            ORDER BY gt.submitted_at DESC
            LIMIT %s OFFSET %s
            """,
            params_filter + [limit, offset],
        )
        rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT COUNT(*) FROM gpu_tasks gt
            WHERE gt.task_type = 'search'
              AND gt.status = 'done'
              AND gt.search_task_id IS NOT NULL
              {user_filter}
            """,
            params_filter,
        )
        total = cur.fetchone()[0]
        cur.close()

        tasks = [
            {
                "search_task_id": r[0],
                "user_id": str(r[1]),
                "username": r[2],
                "dataset_id": str(r[3]) if r[3] else None,
                "dataset_name": r[4],
                "submitted_at": r[5].isoformat() if r[5] else None,
                "completed_at": r[6].isoformat() if r[6] else None,
                "gpu_seconds": r[7],
                "hit_count": r[8],
            }
            for r in rows
        ]
        return {"tasks": tasks, "total": total, "has_more": offset + limit < total}
    finally:
        if conn:
            pool.putconn(conn)


def blocking_get_search_hits(search_task_id: str, db_table: str | None) -> List[dict]:
    """Return full hit details for a search task, joined with protein metadata if available."""
    pool = get_pool()
    conn = None
    try:
        conn = pool.getconn()
        cur = conn.cursor()

        if db_table:
            try:
                cur.execute(
                    f"""
                    SELECT
                        sh.rank,
                        sh.protein_row_id,
                        sh.faiss_distance,
                        p.original_header,
                        p.sequence,
                        p.ph_processed,
                        p.ko_number,
                        p.ec_number
                    FROM search_history_hits sh
                    LEFT JOIN "{db_table}" p ON p.id = sh.protein_row_id
                    WHERE sh.search_task_id = %s
                    ORDER BY sh.rank
                    """,
                    (search_task_id,),
                )
                rows = cur.fetchall()
                cur.close()
                return [
                    {
                        "rank": r[0],
                        "protein_row_id": r[1],
                        "faiss_distance": r[2],
                        "original_header": r[3],
                        "sequence": r[4],
                        "ph_processed": r[5],
                        "ko_number": r[6],
                        "ec_number": r[7],
                    }
                    for r in rows
                ]
            except Exception:
                logger.warning(
                    "Protein table '%s' unavailable for task %s, returning raw hits",
                    db_table,
                    search_task_id,
                )
                conn.rollback()

        # Fallback: no metadata
        cur.execute(
            """
            SELECT rank, protein_row_id, faiss_distance
            FROM search_history_hits
            WHERE search_task_id = %s
            ORDER BY rank
            """,
            (search_task_id,),
        )
        rows = cur.fetchall()
        cur.close()
        return [
            {"rank": r[0], "protein_row_id": r[1], "faiss_distance": r[2]}
            for r in rows
        ]
    finally:
        if conn:
            pool.putconn(conn)
