"""
CLI entry point: python -m app.cli

Connects to the daemon as admin and starts the interactive REPL.
"""
import argparse
import sys

from app.core import config_loader
from app.cli.ipc_client import init_client, IpcError


def main():
    parser = argparse.ArgumentParser(description="ProtFaiss interactive CLI")
    parser.add_argument("--host", default=None, help="Daemon IPC host (default from config.yml)")
    parser.add_argument("--port", type=int, default=None, help="Daemon IPC port (default from config.yml)")
    args = parser.parse_args()

    host = args.host or config_loader.get("daemon", "ipc_host", "127.0.0.1")
    port = args.port or config_loader.get("daemon", "ipc_port", 9002)

    print("\033[1;36m╭─────────────────────────────────────╮\033[0m")
    print("\033[1;36m│\033[0m  \033[1mProtFaiss Interactive Console\033[0m      \033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Connecting to {host}:{port}…\033[1;36m\033[0m      \033[1;36m│\033[0m")
    print("\033[1;36m╰─────────────────────────────────────╯\033[0m")
    try:
        client = init_client(host, port)
    except (ConnectionRefusedError, OSError) as e:
        print(f"Cannot connect to daemon: {e}")
        print("Make sure the daemon is running: python -m app.daemon")
        sys.exit(1)

    # Identify as admin: get the bootstrap admin user ID
    try:
        health = client.call("system.health", {})
        print(f"\033[32m✓\033[0m Daemon status: {health.get('status', 'unknown')}")
    except IpcError as e:
        print(f"Daemon health check failed: {e.message}")
        sys.exit(1)

    # Resolve admin user ID via IPC (avoids direct DB access from CLI process)
    try:
        import os
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        data = client.call("user.list", {"limit": 100, "offset": 0})
        for u in data.get("users", []):
            if u.get("username") == admin_username:
                client.set_admin_user_id(u["id"])
                break
    except Exception:
        pass  # Non-fatal: user_id stays None, daemon still accepts cli source as admin

    print("Type \033[33mhelp\033[0m for commands, \033[33mquit\033[0m to exit.\n")

    from app.cli.repl import run_repl
    run_repl()


if __name__ == "__main__":
    main()
