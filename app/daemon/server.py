"""
Asyncio TCP server for the daemon IPC channel.

Each connection is persistent. Messages are length-prefixed JSON frames
(see protocol.py). The server handles one request at a time per connection
but multiple connections are served concurrently.
"""
import asyncio
import traceback

from .protocol import read_message, write_message, make_response
from .handler import dispatch, HandlerError, _load_operations

_server: asyncio.Server | None = None


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer = writer.get_extra_info("peername", "unknown")
    try:
        while True:
            try:
                message = await read_message(reader)
            except asyncio.IncompleteReadError:
                break  # client disconnected cleanly

            req_id = message.get("id", "?")
            try:
                result = await dispatch(message)
                await write_message(writer, make_response(req_id, result=result))
            except HandlerError as e:
                await write_message(
                    writer,
                    make_response(req_id, error={"code": e.code, "message": e.message}),
                )
            except Exception as e:
                traceback.print_exc()
                await write_message(
                    writer,
                    make_response(req_id, error={"code": 500, "message": str(e)}),
                )
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_server(host: str, port: int) -> asyncio.Server:
    """Start the IPC TCP server. Call once from daemon __main__."""
    global _server
    _load_operations()
    _server = await asyncio.start_server(_handle_connection, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in _server.sockets)
    print(f"[daemon] IPC server listening on {addrs}")
    return _server


async def stop_server() -> None:
    """Gracefully stop the IPC server."""
    global _server
    if _server:
        _server.close()
        await _server.wait_closed()
        _server = None
        print("[daemon] IPC server stopped")
