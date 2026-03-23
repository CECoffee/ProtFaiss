"""
Async IPC client for the API service.

Maintains a small pool of persistent TCP connections to the daemon.
Usage:
    from app.api.ipc_client import get_client
    result = await get_client().call("search.submit", params, context)
"""
import asyncio
import uuid
from typing import Any

from app.daemon.protocol import read_message, write_message, make_request
from app.core import config_loader

_POOL_SIZE = 4


class IpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _Connection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self._lock = asyncio.Lock()

    async def call(self, method: str, params: dict, context: dict) -> Any:
        req_id = str(uuid.uuid4())
        msg = make_request(method, params, context, req_id)
        async with self._lock:
            await write_message(self.writer, msg)
            response = await read_message(self.reader)
        if response.get("error"):
            err = response["error"]
            raise IpcError(err.get("code", 500), err.get("message", "daemon error"))
        return response.get("result")

    def is_alive(self) -> bool:
        return not self.writer.is_closing()

    async def close(self):
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass


class IpcClient:
    def __init__(self):
        self._pool: list[_Connection] = []
        self._pool_lock = asyncio.Lock()
        self._host: str = "127.0.0.1"
        self._port: int = 9002

    async def connect(self):
        self._host = config_loader.get("daemon", "ipc_host", "127.0.0.1")
        self._port = config_loader.get("daemon", "ipc_port", 9002)
        for _ in range(_POOL_SIZE):
            conn = await self._new_connection()
            self._pool.append(conn)
        print(f"[api] IPC client connected to {self._host}:{self._port} ({_POOL_SIZE} connections)")

    async def _new_connection(self) -> _Connection:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        return _Connection(reader, writer)

    async def _acquire(self) -> _Connection:
        async with self._pool_lock:
            for conn in self._pool:
                if conn.is_alive() and not conn._lock.locked():
                    return conn
            # All busy or dead — open a new one
            conn = await self._new_connection()
            self._pool.append(conn)
            return conn

    async def call(self, method: str, params: dict, context: dict) -> Any:
        conn = await self._acquire()
        try:
            return await conn.call(method, params, context)
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            # Reconnect once
            await conn.close()
            async with self._pool_lock:
                if conn in self._pool:
                    self._pool.remove(conn)
            new_conn = await self._new_connection()
            async with self._pool_lock:
                self._pool.append(new_conn)
            return await new_conn.call(method, params, context)

    async def close(self):
        async with self._pool_lock:
            for conn in self._pool:
                await conn.close()
            self._pool.clear()


_client: IpcClient | None = None


def get_client() -> IpcClient:
    assert _client is not None, "IPC client not initialized"
    return _client


async def init_client():
    global _client
    _client = IpcClient()
    await _client.connect()


async def close_client():
    global _client
    if _client:
        await _client.close()
        _client = None
