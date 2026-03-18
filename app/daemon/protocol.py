"""
Wire format: 4-byte big-endian uint32 length prefix + UTF-8 JSON payload.

    [4 bytes: payload length][JSON bytes]

Both daemon server and IPC clients (API, CLI) use these helpers.
"""
import asyncio
import json
import struct
from typing import Any

_HEADER = struct.Struct(">I")  # big-endian unsigned int, 4 bytes


async def read_message(reader: asyncio.StreamReader) -> dict:
    """Read one length-prefixed JSON message from an asyncio StreamReader."""
    header = await reader.readexactly(_HEADER.size)
    (length,) = _HEADER.unpack(header)
    payload = await reader.readexactly(length)
    return json.loads(payload.decode("utf-8"))


async def write_message(writer: asyncio.StreamWriter, data: Any) -> None:
    """Write one length-prefixed JSON message to an asyncio StreamWriter."""
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = _HEADER.pack(len(payload))
    writer.write(header + payload)
    await writer.drain()


def encode_message(data: Any) -> bytes:
    """Encode a message to bytes (for sync clients)."""
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return _HEADER.pack(len(payload)) + payload


def decode_message(raw: bytes) -> dict:
    """Decode a length-prefixed message from a complete byte buffer."""
    (length,) = _HEADER.unpack(raw[:_HEADER.size])
    return json.loads(raw[_HEADER.size: _HEADER.size + length].decode("utf-8"))


def make_request(method: str, params: dict, context: dict, req_id: str = None) -> dict:
    import uuid
    return {
        "id": req_id or str(uuid.uuid4()),
        "method": method,
        "params": params,
        "context": context,
    }


def make_response(req_id: str, result: Any = None, error: dict = None) -> dict:
    return {"id": req_id, "result": result, "error": error}


def make_stream_frame(req_id: str, result: Any, final: bool = False) -> dict:
    return {"id": req_id, "stream": not final, "result": result, "error": None}
