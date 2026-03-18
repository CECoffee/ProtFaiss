"""
Synchronous IPC client for the CLI.

The CLI is a blocking REPL, so we use a plain socket instead of asyncio.
Reuses the same length-prefixed JSON wire format as the async client.
"""
import json
import socket
import struct
import uuid
from typing import Any

from app.core import config_loader

_HEADER = struct.Struct(">I")


class IpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class CliIpcClient:
    def __init__(self, host: str = None, port: int = None):
        self._host = host or config_loader.get("daemon", "ipc_host", "127.0.0.1")
        self._port = port or config_loader.get("daemon", "ipc_port", 9812)
        self._sock: socket.socket | None = None
        self._admin_context: dict = {"source": "cli", "role": "admin", "user_id": None}

    def connect(self) -> None:
        self._sock = socket.create_connection((self._host, self._port), timeout=30)
        self._sock.settimeout(120)  # generous timeout for long operations

    def set_admin_user_id(self, user_id: str) -> None:
        self._admin_context = {"source": "cli", "role": "admin", "user_id": user_id}

    def call(self, method: str, params: dict) -> Any:
        req_id = str(uuid.uuid4())
        msg = {
            "id": req_id,
            "method": method,
            "params": params,
            "context": self._admin_context,
        }
        payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        self._sock.sendall(_HEADER.pack(len(payload)) + payload)

        # Read response header
        header = self._recv_exact(_HEADER.size)
        (length,) = _HEADER.unpack(header)
        body = self._recv_exact(length)
        response = json.loads(body.decode("utf-8"))

        if response.get("error"):
            err = response["error"]
            raise IpcError(err.get("code", 500), err.get("message", "daemon error"))
        return response.get("result")

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Daemon closed connection")
            buf += chunk
        return buf

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


_client: CliIpcClient | None = None


def get_client() -> CliIpcClient:
    assert _client is not None, "CLI IPC client not connected"
    return _client


def init_client(host: str = None, port: int = None) -> CliIpcClient:
    global _client
    _client = CliIpcClient(host, port)
    _client.connect()
    return _client
