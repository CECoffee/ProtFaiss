"""
Async TCP client for dispatching tasks to a remote GPU worker node.

Uses the same length-prefixed JSON protocol as app/daemon/protocol.py.
Maintains a single persistent connection per worker node.
The control plane connects to each registered worker on task dispatch.
"""
import asyncio
import uuid
from typing import Optional

from app.daemon.protocol import read_message, write_message, make_request


class WorkerUnreachableError(Exception):
    """Raised when a worker cannot be reached after all retries are exhausted."""


class WorkerClient:
    def __init__(self, node_id: str, host: str, port: int):
        self.node_id = node_id
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._connected = False

    async def connect(self, timeout: float = 10.0) -> None:
        async with self._lock:
            if self._connected:
                return
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=timeout,
            )
            self._connected = True
            print(f"[worker_client] Connected to {self.node_id} @ {self.host}:{self.port}")

    async def close(self) -> None:
        async with self._lock:
            self._connected = False
            if self._writer:
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                except Exception:
                    pass
            self._reader = None
            self._writer = None

    async def _close_connection_locked(self) -> None:
        """Close the current connection without acquiring the lock (caller must hold it)."""
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def call(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        """Send a request and wait for a response. Retries up to retry_num times on connection failure."""
        from app.core import config_loader
        retry_num = config_loader.get("cluster", "retry_num", 3)

        last_error: Optional[Exception] = None
        for attempt in range(retry_num + 1):
            try:
                async with self._lock:
                    if not self._connected:
                        self._reader, self._writer = await asyncio.wait_for(
                            asyncio.open_connection(self.host, self.port),
                            timeout=10.0,
                        )
                        self._connected = True
                    req = make_request(method, params, context={"role": "system"}, req_id=str(uuid.uuid4()))
                    await write_message(self._writer, req)
                    response = await asyncio.wait_for(read_message(self._reader), timeout=timeout)
                # Lock released here — check error outside the lock
                if response.get("error"):
                    err = response["error"]
                    raise RuntimeError(f"Worker error [{err.get('code')}]: {err.get('message', err)}")
                return response.get("result", {})
            except (ConnectionError, OSError, BrokenPipeError, asyncio.TimeoutError) as e:
                last_error = e
                # Reset connection state before next attempt
                async with self._lock:
                    await self._close_connection_locked()
                if attempt < retry_num:
                    print(
                        f"[worker_client] {self.node_id} RPC '{method}' failed "
                        f"(attempt {attempt + 1}/{retry_num + 1}): {e}, retrying in 1s..."
                    )
                    await asyncio.sleep(1)

        raise WorkerUnreachableError(
            f"Worker {self.node_id} unreachable after {retry_num} retries: {last_error}"
        )

    async def dispatch_search(self, task_id: str, search_params: dict) -> None:
        """Send a search task to the worker. Worker writes result to Redis."""
        await self.call("worker.search", {"task_id": task_id, **search_params}, timeout=5.0)

    async def dispatch_build(self, gpu_task_id: str, build_config: dict) -> None:
        """Send a build task to the worker. Worker updates DB progress directly."""
        await self.call("worker.build", {"gpu_task_id": gpu_task_id, "config": build_config}, timeout=5.0)

    async def unload_dataset(self, dataset_id: str) -> None:
        """Ask worker to evict a dataset from its VRAM cache."""
        try:
            await self.call("worker.unload", {"dataset_id": dataset_id}, timeout=10.0)
        except Exception as e:
            print(f"[worker_client] unload_dataset error on {self.node_id}: {e}")

    @property
    def is_connected(self) -> bool:
        return self._connected
