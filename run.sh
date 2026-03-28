#!/bin/bash
# Skyhunter V2 — start the web UI server (uses existing venv from setup.sh).
# If something is already on the port, kill it and restart in this shell.

set -e
cd "$(dirname "$0")"

PORT=5050
VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/python" ]; then
  echo "Run ./setup.sh first to install dependencies."
  exit 1
fi

# Force-kill anything on the port and wait until it's free
for i in 1 2 3 4 5 6; do
  PIDS=$(lsof -ti ":$PORT" 2>/dev/null) || true
  if [ -z "$PIDS" ]; then
    break
  fi
  echo "Killing process(es) on port $PORT: $PIDS (attempt $i/6) ..."
  for p in $PIDS; do
    kill -9 "$p" 2>/dev/null || true
  done
  sleep 3
done
PIDS=$(lsof -ti ":$PORT" 2>/dev/null) || true
if [ -n "$PIDS" ]; then
  echo "Port $PORT still in use. Run: kill -9 $PIDS"
  exit 1
fi

echo "Starting Skyhunter V2 server ..."
echo "  Local:    http://localhost:$PORT"
if [ -n "$WSL_DISTRO_NAME" ] || grep -qi microsoft /proc/version 2>/dev/null; then
  WSL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  [ -n "$WSL_IP" ] && echo "  Windows:  http://${WSL_IP}:$PORT"
fi
echo "  Ctrl+C to stop"
echo ""

exec "$VENV_DIR/bin/python" web_ui.py --host 0.0.0.0 --port "$PORT" "$@"
