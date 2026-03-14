"""
Fair-share priority calculation.

Users who have consumed more GPU time recently get a higher priority number
(lower priority = scheduled later). Uses exponential decay so old usage fades.
"""
from typing import Dict
from app.core.db import get_pool as get_db_pool


def blocking_get_decayed_usage() -> Dict[str, float]:
    """Returns {user_id: decayed_gpu_seconds} for all users."""
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, decayed_gpu_seconds FROM user_gpu_usage")
            return {str(row[0]): float(row[1]) for row in cur.fetchall()}
    finally:
        pool.putconn(conn)


def blocking_record_gpu_usage(user_id: str, gpu_seconds: float) -> None:
    """Add gpu_seconds to user's usage counters."""
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_gpu_usage (user_id, total_gpu_seconds, decayed_gpu_seconds)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    total_gpu_seconds   = user_gpu_usage.total_gpu_seconds + EXCLUDED.total_gpu_seconds,
                    decayed_gpu_seconds = user_gpu_usage.decayed_gpu_seconds + EXCLUDED.decayed_gpu_seconds
                """,
                (user_id, gpu_seconds, gpu_seconds),
            )
            conn.commit()
    finally:
        pool.putconn(conn)


def compute_fair_share_penalty(user_id: str, usage_map: Dict[str, float]) -> float:
    """
    Returns a priority penalty (0–50) based on relative GPU usage.
    Users with more usage get a higher penalty (lower scheduling priority).
    """
    if not usage_map:
        return 0.0
    user_usage = usage_map.get(user_id, 0.0)
    avg_usage = sum(usage_map.values()) / len(usage_map)
    if avg_usage == 0:
        return 0.0
    ratio = user_usage / avg_usage
    return min(50.0, ratio * 25.0)
