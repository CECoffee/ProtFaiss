"""\\config and \\reload commands."""
import yaml

from app.cli.ipc_client import get_client, IpcError


def cmd_config(args: list[str]) -> None:
    client = get_client()
    try:
        cfg = client.call("config.get", {})
        print(yaml.dump(cfg, default_flow_style=False, allow_unicode=True), end="")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_reload(args: list[str]) -> None:
    client = get_client()
    try:
        result = client.call("config.reload", {})
        print(f"Config reloaded: {result.get('status')}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
