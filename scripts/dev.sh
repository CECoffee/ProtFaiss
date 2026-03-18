#!/usr/bin/env bash
# dev.sh — Start daemon, API backend, and Vue frontend.
# Usage: bash scripts/dev.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$DAEMON_PID" "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

cd "$PROJECT_ROOT"

# Daemon
echo "[daemon] Starting core daemon on 127.0.0.1:9812 ..."
python -m app.daemon &
DAEMON_PID=$!

# Wait for daemon to be ready
echo "[daemon] Waiting for daemon to start..."
for i in $(seq 1 30); do
  if python -c "
import socket, sys
try:
    s = socket.create_connection(('127.0.0.1', 9812), timeout=1)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo "[daemon] Ready."
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo "[daemon] ERROR: Daemon did not start in 30s. Check logs."
    kill "$DAEMON_PID" 2>/dev/null
    exit 1
  fi
done

# API
echo "[api] Starting FastAPI on http://localhost:8000 ..."
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Frontend
cd "$PROJECT_ROOT/frontend"
echo "[frontend] Starting Vite dev server on http://localhost:5173 ..."
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  Daemon   → 127.0.0.1:9812 (IPC)"
echo "  Backend  → http://localhost:8000"
echo "  Frontend → http://localhost:5173"
echo "  CLI      → python -m app.cli"
echo ""
echo "Press Ctrl+C to stop all."

wait
