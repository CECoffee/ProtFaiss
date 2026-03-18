"""
Interactive REPL for the FaaIndex CLI.

Uses prompt_toolkit for cross-platform readline support, history, and
tab completion. Falls back to plain input() if prompt_toolkit is not installed.
"""
import os
import shlex
from pathlib import Path

from app.cli.ipc_client import get_client, IpcError
from app.cli.commands import (
    search, build, datasets, gpu, users, config as cfg_cmd, system,
)

_HISTORY_FILE = Path(os.path.expanduser("~/.protfaiss/cli_history"))

_COMMANDS = {
    r"\search":       (search.run,              "\\search <seq> [--top_k N] [--pooling mean|max]"),
    r"\build":        (build.cmd_build,          "\\build <fasta_path> [--name N] [--algorithm A]"),
    r"\build-status": (build.cmd_build_status,   "\\build-status <dataset_id>"),
    r"\datasets":     (datasets.cmd_datasets,    "\\datasets"),
    r"\switch":       (datasets.cmd_switch,      "\\switch <dataset_id>"),
    r"\delete":       (datasets.cmd_delete,      "\\delete <dataset_id>"),
    r"\visibility":   (datasets.cmd_visibility,  "\\visibility <dataset_id> <public|private>"),
    r"\gpu":          (gpu.cmd_gpu,              "\\gpu"),
    r"\gpu-status":   (gpu.cmd_gpu_status,       "\\gpu-status"),
    r"\cancel":       (gpu.cmd_cancel,           "\\cancel <task_id>"),
    r"\users":        (users.cmd_users,          "\\users"),
    r"\user":         (users.cmd_user,           "\\user <user_id>"),
    r"\useradd":      (users.cmd_useradd,        "\\useradd <username> <password> [email]"),
    r"\userdel":      (users.cmd_userdel,        "\\userdel <user_id>"),
    r"\config":       (cfg_cmd.cmd_config,       "\\config"),
    r"\reload":       (cfg_cmd.cmd_reload,       "\\reload"),
    r"\status":       (system.cmd_status,        "\\status"),
    r"\health":       (system.cmd_health,        "\\health"),
}


def _print_help() -> None:
    print("\nAvailable commands:")
    for usage in _COMMANDS.values():
        print(f"  {usage[1]}")
    print("  \\help")
    print("  \\quit  (or Ctrl+D)")
    print()


def _dispatch(line: str) -> bool:
    """Parse and dispatch one input line. Returns False to exit."""
    line = line.strip()
    if not line:
        return True

    try:
        parts = shlex.split(line)
    except ValueError as e:
        print(f"Parse error: {e}")
        return True

    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in (r"\quit", r"\exit", r"\q"):
        return False
    if cmd in (r"\help", r"\h", r"\?"):
        _print_help()
        return True

    handler_entry = _COMMANDS.get(cmd)
    if handler_entry is None:
        print(f"Unknown command: {cmd}  (type \\help for list)")
        return True

    try:
        handler_entry[0](args)
    except KeyboardInterrupt:
        print()
    except Exception as e:
        print(f"Command error: {e}")

    return True


def _make_completer():
    try:
        from prompt_toolkit.completion import WordCompleter
        return WordCompleter(list(_COMMANDS.keys()) + [r"\help", r"\quit"], sentence=True)
    except ImportError:
        return None


def run_repl() -> None:
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory

        session = PromptSession(
            history=FileHistory(str(_HISTORY_FILE)),
            completer=_make_completer(),
            complete_while_typing=False,
        )

        def _prompt() -> str | None:
            try:
                return session.prompt("protfaiss> ")
            except KeyboardInterrupt:
                return ""
            except EOFError:
                return None

    except ImportError:
        # Fallback: plain input()
        def _prompt() -> str | None:
            try:
                return input("protfaiss> ")
            except (KeyboardInterrupt, EOFError):
                return None

    while True:
        line = _prompt()
        if line is None:
            print("\nGoodbye.")
            break
        if not _dispatch(line):
            print("Goodbye.")
            break
