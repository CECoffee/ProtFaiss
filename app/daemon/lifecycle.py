"""
Daemon lifecycle: PID file management and signal handling.
"""
import os
import signal
import sys
from pathlib import Path

from app.core import config_loader

_pid_file: Path | None = None


def _get_pid_dir() -> Path:
    raw = config_loader.get("daemon", "pid_dir", "~/.protfaiss")
    return Path(os.path.expanduser(raw))


def write_pid() -> Path:
    """Write current PID to ~/.protfaiss/daemon.pid. Returns the path."""
    global _pid_file
    pid_dir = _get_pid_dir()
    pid_dir.mkdir(parents=True, exist_ok=True)
    _pid_file = pid_dir / "daemon.pid"
    _pid_file.write_text(str(os.getpid()), encoding="utf-8")
    print(f"[daemon] PID {os.getpid()} written to {_pid_file}")
    return _pid_file


def remove_pid() -> None:
    """Remove the PID file if it exists."""
    global _pid_file
    if _pid_file and _pid_file.exists():
        try:
            _pid_file.unlink()
        except OSError:
            pass
    _pid_file = None


def read_pid() -> int | None:
    """Read the daemon PID from the PID file, or None if not running."""
    pid_file = _get_pid_dir() / "daemon.pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def register_signal_handlers(shutdown_callback) -> None:
    """
    Register SIGINT (Ctrl+C) and platform-specific termination signals.
    shutdown_callback is a zero-argument callable that triggers graceful shutdown.
    """
    def _handler(signum, frame):
        print(f"\n[daemon] Received signal {signum}, shutting down...")
        shutdown_callback()

    signal.signal(signal.SIGINT, _handler)

    if sys.platform == "win32":
        # SIGBREAK is Ctrl+Break on Windows
        try:
            signal.signal(signal.SIGBREAK, _handler)
        except (OSError, AttributeError):
            pass
    else:
        signal.signal(signal.SIGTERM, _handler)
