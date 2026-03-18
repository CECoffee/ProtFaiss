"""
CLI entry point: python -m app.cli

Connects to the daemon as admin and starts the interactive REPL.
"""
import argparse
import sys

from app.core import config_loader
from app.cli.ipc_client import init_client, IpcError


def main():
    parser = argparse.ArgumentParser(description="FaaIndex interactive CLI")
    parser.add_argument("--host", default=None, help="Daemon IPC host (default from config.yml)")
    parser.add_argument("--port", type=int, default=None, help="Daemon IPC port (default from config.yml)")
    args = parser.parse_args()

    host = args.host or config_loader.get("daemon", "ipc_host", "127.0.0.1")
    port = args.port or config_loader.get("daemon", "ipc_port", 9812)

    print(f"FaaIndex CLI — connecting to daemon at {host}:{port}…")
    try:
        client = init_client(host, port)
    except (ConnectionRefusedError, OSError) as e:
        print(f"Cannot connect to daemon: {e}")
        print("Make sure the daemon is running: python -m app.daemon")
        sys.exit(1)

    # Identify as admin: get the bootstrap admin user ID
    try:
        health = client.call("system.health", {})
        print(f"Connected. Daemon status: {health.get('status', 'unknown')}")
    except IpcError as e:
        print(f"Daemon health check failed: {e.message}")
        sys.exit(1)

    # Resolve admin user ID for context
    try:
        import os
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        from app.auth.db_operations import blocking_get_user_by_username
        user = blocking_get_user_by_username(admin_username)
        if user:
            client.set_admin_user_id(user["id"])
    except Exception:
        pass  # Non-fatal: user_id stays None, daemon still accepts cli source as admin

    print("Type \\help for commands, \\quit to exit.\n")

    from app.cli.repl import run_repl
    run_repl()


if __name__ == "__main__":
    main()
