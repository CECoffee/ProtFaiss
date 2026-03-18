"""\\status and \\health commands."""
from app.cli.ipc_client import get_client, IpcError


def cmd_status(args: list[str]) -> None:
    client = get_client()
    try:
        health = client.call("system.health", {})
        stats = client.call("system.stats", {})
        print("\nHealth:")
        for k, v in health.items():
            print(f"  {k}: {v}")
        print("\nStats:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_health(args: list[str]) -> None:
    client = get_client()
    try:
        result = client.call("system.health", {})
        for k, v in result.items():
            print(f"  {k}: {v}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
