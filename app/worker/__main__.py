"""
GPU Worker node entry point: python -m app.worker

Startup sequence:
  1. Log GPU status
  2. Init ESM2 model (loads model to GPU)
  3. Init DB pool
  4. Start worker IPC server (listens for task dispatch from control plane)
  5. Connect to control plane and register
  6. Start heartbeat loop
  7. Wait for shutdown signal

Shutdown sequence:
  1. Cancel heartbeat
  2. Stop IPC server
  3. Close DB pool
"""
import asyncio
import os
import socket

from app.core.config import ESM2_MODEL_DIR
from app.core import config_loader
from app.daemon.lifecycle import register_signal_handlers


async def _run():
    from app.core import gpu as _gpu
    from app.core.encoder import init_model
    from app.core.db import init_db_pool, close_db_pool
    from app.core.redis_client import init_client as init_redis, close_client as close_redis
    from app.worker.service import start_worker_server, stop_worker_server
    from app.worker.heartbeat import start_heartbeat, stop_heartbeat

    node_id = config_loader.get("worker", "node_id", "") or socket.gethostname()
    host = config_loader.get("worker", "host", "0.0.0.0")
    port = config_loader.get("worker", "port", 9820)

    print(f"[worker] Starting node: {node_id} on {host}:{port}")
    _gpu.log_gpu_status()

    # Detect available GPU slots and validate against config
    gpu_devices = _gpu.get_available_devices()
    physical_slots = len(gpu_devices) if gpu_devices else 1
    configured_slots = config_loader.get("scheduler", "total_gpu_slots", 1)
    if configured_slots > physical_slots:
        print(
            f"[worker] WARNING: scheduler.total_gpu_slots={configured_slots} exceeds "
            f"available GPU count ({physical_slots}); capping to {physical_slots}."
        )
        gpu_slots = physical_slots
    else:
        gpu_slots = configured_slots

    model_dir = config_loader.get("storage", "models_root", "") or ESM2_MODEL_DIR
    init_model(model_dir)
    init_db_pool()
    await init_redis()

    server = await start_worker_server(host, port)

    # Register with control plane
    cp_host = config_loader.get("cluster", "control_plane_host", "127.0.0.1")
    cp_port = config_loader.get("cluster", "control_plane_port", 9002)
    advertise_host = _resolve_advertise_host(host)

    await _register_with_control_plane(
        cp_host, cp_port, node_id,
        address=f"{advertise_host}:{port}",
        gpu_count=len(gpu_devices) if gpu_devices else 1,
        gpu_slots=gpu_slots,
    )

    heartbeat_task = asyncio.create_task(
        start_heartbeat(
            node_id, cp_host, cp_port,
            address=f"{advertise_host}:{port}",
            gpu_count=len(gpu_devices) if gpu_devices else 1,
            gpu_slots=gpu_slots,
        )
    )

    stop_event = asyncio.Event()
    register_signal_handlers(stop_event.set)

    print(f"[worker] Ready. Node: {node_id}")
    await stop_event.wait()

    print("[worker] Shutting down...")
    await stop_heartbeat(heartbeat_task)
    await _deregister_from_control_plane(cp_host, cp_port, node_id)
    await stop_worker_server()
    close_db_pool()
    await close_redis()
    print("[worker] Goodbye.")


def _resolve_advertise_host(bind_host: str) -> str:
    """Resolve the address workers advertise to the control plane."""
    if bind_host not in ("0.0.0.0", ""):
        return bind_host
    # Try to get the primary outbound IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return socket.gethostname()


async def _register_with_control_plane(
    cp_host: str,
    cp_port: int,
    node_id: str,
    address: str,
    gpu_count: int,
    gpu_slots: int,
) -> None:
    from app.daemon.protocol import read_message, write_message, make_request
    delay = 2
    attempt = 0
    while True:
        attempt += 1
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(cp_host, cp_port),
                timeout=10.0,
            )
            req = make_request(
                "worker.register",
                {
                    "node_id": node_id,
                    "address": address,
                    "gpu_count": gpu_count,
                    "gpu_slots": gpu_slots,
                    "capabilities": ["encode", "search", "build"],
                },
                context={"role": "system"},
            )
            await write_message(writer, req)
            response = await asyncio.wait_for(read_message(reader), timeout=10.0)
            writer.close()
            await writer.wait_closed()
            if response.get("error"):
                raise RuntimeError(f"Registration rejected: {response['error']}")
            print(f"[worker] Registered with control plane @ {cp_host}:{cp_port}")
            return
        except Exception as e:
            print(f"[worker] Registration attempt {attempt} failed: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def _deregister_from_control_plane(
    cp_host: str,
    cp_port: int,
    node_id: str,
) -> None:
    from app.daemon.protocol import read_message, write_message, make_request
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(cp_host, cp_port),
            timeout=5.0,
        )
        req = make_request(
            "worker.deregister",
            {"node_id": node_id},
            context={"role": "system"},
        )
        await write_message(writer, req)
        await asyncio.wait_for(read_message(reader), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        print(f"[worker] Deregistered from control plane @ {cp_host}:{cp_port}")
    except Exception as e:
        print(f"[worker] WARNING: Failed to deregister from control plane: {e}")


if __name__ == "__main__":
    asyncio.run(_run())
