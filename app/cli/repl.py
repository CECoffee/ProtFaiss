"""
Interactive REPL for the FaaIndex CLI.

Uses prompt_toolkit for cross-platform readline support, history, tab
completion, bottom toolbar hints, and styled output.
Falls back to plain input() if prompt_toolkit is not installed.
"""
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from app.cli.ipc_client import get_client, IpcError
from app.cli.commands import (
    search, build, datasets, gpu, users, config as cfg_cmd, system,
)

_HISTORY_FILE = Path(os.path.expanduser("~/.protfaiss/cli_history"))


@dataclass
class CommandEntry:
    handler: Callable
    usage: str
    description: str
    category: str
    flags: List[str] = field(default_factory=list)
    flag_values: dict = field(default_factory=dict)


_COMMANDS: dict[str, CommandEntry] = {
    "search": CommandEntry(
        handler=search.run,
        usage="search <seq> [--top_k N] [--pooling mean|max]",
        description="Search for similar protein sequences",
        category="Search",
        flags=["--top_k", "--pooling"],
        flag_values={"--pooling": ["mean", "max"]},
    ),
    "build": CommandEntry(
        handler=build.cmd_build,
        usage="build <fasta_path> [--name N] [--algorithm flat|ivfpq|hnsw]",
        description="Build FAISS index from FASTA file",
        category="Build",
        flags=["--name", "--algorithm"],
        flag_values={"--algorithm": ["flat", "ivfpq", "hnsw"]},
    ),
    "build-status": CommandEntry(
        handler=build.cmd_build_status,
        usage="build-status <dataset_id>",
        description="Check build job status",
        category="Build",
    ),
    "datasets": CommandEntry(
        handler=datasets.cmd_datasets,
        usage="datasets",
        description="List all datasets",
        category="Datasets",
    ),
    "switch": CommandEntry(
        handler=datasets.cmd_switch,
        usage="switch <dataset_id>",
        description="Switch active dataset",
        category="Datasets",
    ),
    "delete": CommandEntry(
        handler=datasets.cmd_delete,
        usage="delete <dataset_id>",
        description="Delete a dataset",
        category="Datasets",
    ),
    "visibility": CommandEntry(
        handler=datasets.cmd_visibility,
        usage="visibility <dataset_id> <public|private>",
        description="Set dataset visibility",
        category="Datasets",
        flags=["public", "private"],
    ),
    "gpu": CommandEntry(
        handler=gpu.cmd_gpu,
        usage="gpu",
        description="Show GPU queue (user view)",
        category="GPU",
    ),
    "gpu-status": CommandEntry(
        handler=gpu.cmd_gpu_status,
        usage="gpu-status",
        description="Show full GPU queue (admin)",
        category="GPU",
    ),
    "cancel": CommandEntry(
        handler=gpu.cmd_cancel,
        usage="cancel <task_id>",
        description="Cancel a GPU task",
        category="GPU",
    ),
    "users": CommandEntry(
        handler=users.cmd_users,
        usage="users",
        description="List all users",
        category="Users",
    ),
    "user": CommandEntry(
        handler=users.cmd_user,
        usage="user <user_id>",
        description="Show user details",
        category="Users",
    ),
    "useradd": CommandEntry(
        handler=users.cmd_useradd,
        usage="useradd <username> <password> [email]",
        description="Create a new user",
        category="Users",
    ),
    "userdel": CommandEntry(
        handler=users.cmd_userdel,
        usage="userdel <user_id>",
        description="Delete a user",
        category="Users",
    ),
    "config": CommandEntry(
        handler=cfg_cmd.cmd_config,
        usage="config",
        description="Show current config",
        category="Config",
    ),
    "reload": CommandEntry(
        handler=cfg_cmd.cmd_reload,
        usage="reload",
        description="Hot-reload config from disk",
        category="Config",
    ),
    "status": CommandEntry(
        handler=system.cmd_status,
        usage="status",
        description="Show system status",
        category="System",
    ),
    "health": CommandEntry(
        handler=system.cmd_health,
        usage="health",
        description="Daemon health check",
        category="System",
    ),
}

_CATEGORY_ORDER = ["Search", "Build", "Datasets", "GPU", "Users", "Config", "System"]


def _print_help() -> None:
    from itertools import groupby
    grouped: dict[str, list] = {}
    for name, entry in _COMMANDS.items():
        grouped.setdefault(entry.category, []).append((name, entry))

    print()
    for cat in _CATEGORY_ORDER:
        if cat not in grouped:
            continue
        print(f"  \033[1;36m{cat}\033[0m")
        for name, entry in grouped[cat]:
            print(f"    \033[33m{entry.usage:<48}\033[0m  {entry.description}")
    print(f"    \033[33m{'help':<48}\033[0m  Show this help")
    print(f"    \033[33m{'quit':<48}\033[0m  Exit (or Ctrl+D)")
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

    # Strip leading backslash for backward compatibility
    cmd = parts[0].lstrip("\\").lower()
    args = parts[1:]

    if cmd in ("quit", "exit", "q"):
        return False
    if cmd in ("help", "h", "?"):
        _print_help()
        return True

    entry = _COMMANDS.get(cmd)
    if entry is None:
        print(f"Unknown command: {cmd}  (type help for list)")
        return True

    try:
        entry.handler(args)
    except KeyboardInterrupt:
        print()
    except Exception as e:
        print(f"Command error: {e}")

    return True


# ── prompt_toolkit integration ────────────────────────────────────────────────

def _make_completer():
    try:
        from prompt_toolkit.completion import Completer, Completion

        class ProtFaissCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor
                parts = text.split()
                ends_with_space = text.endswith(" ")

                if not parts or (len(parts) == 1 and not ends_with_space):
                    # Complete command name
                    word = parts[0].lstrip("\\") if parts else ""
                    for name, entry in sorted(_COMMANDS.items()):
                        if name.startswith(word):
                            yield Completion(
                                name,
                                start_position=-len(word),
                                display_meta=entry.description,
                            )
                    for builtin in ("help", "quit"):
                        if builtin.startswith(word):
                            yield Completion(builtin, start_position=-len(word))
                    return

                cmd = parts[0].lstrip("\\").lower()
                entry = _COMMANDS.get(cmd)
                if not entry:
                    return

                current_word = "" if ends_with_space else parts[-1]

                # Suggest flag values if previous token is a flag with known values
                if not ends_with_space and len(parts) >= 2:
                    prev = parts[-2]
                    if prev in entry.flag_values:
                        for val in entry.flag_values[prev]:
                            if val.startswith(current_word):
                                yield Completion(val, start_position=-len(current_word))
                        return

                if ends_with_space and parts[-1] in entry.flag_values:
                    for val in entry.flag_values[parts[-1]]:
                        yield Completion(val, start_position=0)
                    return

                # Suggest flags
                for flag in entry.flags:
                    if flag.startswith(current_word) and flag not in parts:
                        yield Completion(flag, start_position=-len(current_word))

        return ProtFaissCompleter()
    except ImportError:
        return None


def _make_style():
    try:
        from prompt_toolkit.styles import Style
        return Style.from_dict({
            "prompt":                              "#00cc99 bold",
            "bottom-toolbar":                      "bg:#1e1e1e #888888",
            "completion-menu.completion":          "bg:#2d2d2d #dddddd",
            "completion-menu.completion.current":  "bg:#00cc99 #000000 bold",
            "completion-menu.meta.completion":     "bg:#3a3a3a #999999",
            "completion-menu.meta.completion.current": "bg:#00aa88 #000000",
        })
    except ImportError:
        return None


def run_repl() -> None:
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.formatted_text import HTML, FormattedText

        style = _make_style()
        completer = _make_completer()

        # Bottom toolbar: show usage hint for the command being typed
        def _toolbar():
            try:
                from prompt_toolkit.application import get_app
                buf_text = get_app().current_buffer.text.strip()
            except Exception:
                buf_text = ""

            if buf_text:
                cmd = buf_text.split()[0].lstrip("\\").lower()
                entry = _COMMANDS.get(cmd)
                if entry:
                    import html as _html
                    usage = _html.escape(entry.usage)
                    desc = _html.escape(entry.description)
                    return HTML(f"<b>{usage}</b>  {desc}")

            return HTML(
                "<b>Tab</b> autocomplete  "
                "<b>help</b> commands  "
                "<b>Ctrl+D</b> exit"
            )

        prompt_text = FormattedText([("class:prompt", "protfaiss"), ("", "> ")])

        session = PromptSession(
            history=FileHistory(str(_HISTORY_FILE)),
            completer=completer,
            complete_while_typing=True,
            style=style,
            bottom_toolbar=_toolbar,
        )

        def _prompt() -> Optional[str]:
            try:
                return session.prompt(prompt_text)
            except KeyboardInterrupt:
                return ""
            except EOFError:
                return None

    except ImportError:
        def _prompt() -> Optional[str]:
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
