"""
Worker heartbeat — sends periodic heartbeats to the control plane.

The heartbeat carries the current state of this worker node:
  - cached_datasets: datasets currently loaded in VRAM
  - running_tasks: number of active task executions

The control plane uses heartbeat timestamps to detect dead workers.
If the control plane restarts, heartbeats also trigger re-registration.
"""
import asyncio
import socket
from typing import Optional

from app.core import config_loader


async def start_heartbeat(node_id: str, cp_host: str, cp_port: int) -> None:
    """Main heartbeat coroutine — runs until cancelled."""
    interval = config_loader.get("cluster", "heartbeat_interval", 5)
    while True:
        try:
            await _send_heartbeat(node_id, cp_host, cp_port)
        except Exception as e:
            print(f"[heartbeat] Failed to send heartbeat: {e}")
        await asyncio.sleep(interval)


async def _send_heartbeat(node_id: str, cp_host: str, cp_port: int) -> None:
    from app.search.retriever import _CACHE
    from app.daemon.protocol import read_message, write_message, make_request

    cached_datasets = list(_CACHE.keys())

    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(cp_host, cp_port),
        timeout=5.0,
    )
    try:
        req = make_request(
            "worker.heartbeat",
            {
                "node_id": node_id,
                "cached_datasets": cached_datasets,
                "running_tasks": 0,  # TODO: track active tasks count
            },
            context={"role": "system"},
        )
        await write_message(writer, req)
        await asyncio.wait_for(read_message(reader), timeout=5.0)
    finally:
        writer.close()
        await writer.wait_closed()


async def stop_heartbeat(task: Optional[asyncio.Task]) -> None:
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
