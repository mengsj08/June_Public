#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="8890"
OPEN_BROWSER="1"
PLATFORM_NAME="$(uname -s 2>/dev/null || echo Unknown)"

usage() {
  echo "Usage: ./start.sh [--port PORT] [--no-open]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      PORT="$2"
      shift 2
      ;;
    --no-open)
      OPEN_BROWSER="0"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "Invalid port: $PORT" >&2
  exit 2
fi

install_hint() {
  case "$PLATFORM_NAME" in
    Darwin)
      echo "Install Python 3 from https://www.python.org/downloads/macos/ and Node.js from https://nodejs.org/." >&2
      ;;
    Linux)
      if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
      fi
      case "${ID:-}" in
        ubuntu|debian|linuxmint|pop)
          echo "Install prerequisites with: sudo apt install python3 python3-venv nodejs npm" >&2
          ;;
        fedora|rhel|centos|rocky|almalinux)
          echo "Install prerequisites with: sudo dnf install python3 nodejs npm" >&2
          ;;
        arch|manjaro)
          echo "Install prerequisites with: sudo pacman -S python nodejs npm" >&2
          ;;
        *)
          echo "Install Python 3 with venv plus Node.js/npm using your Linux distribution's package manager." >&2
          ;;
      esac
      ;;
    *)
      echo "Native Windows is not supported. Use WSL, then install Python 3 with venv plus Node.js/npm inside WSL." >&2
      ;;
  esac
}

case "$PLATFORM_NAME" in
  MINGW*|MSYS*|CYGWIN*)
    echo "Native Windows is not supported. Run this launcher inside WSL." >&2
    exit 1
    ;;
esac

missing_prerequisite="0"
for command_name in python3 node npm; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing prerequisite: $command_name" >&2
    missing_prerequisite="1"
  fi
done
if [[ "$missing_prerequisite" == "1" ]]; then
  install_hint
  exit 1
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Missing prerequisite: Python venv module" >&2
  install_hint
  exit 1
fi

VENV_DIR="$ROOT_DIR/.venv"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "[setup] Creating Python virtual environment"
  python3 -m venv "$VENV_DIR"
fi

PYTHON_BIN="$VENV_DIR/bin/python"
if ! "$PYTHON_BIN" -c 'import watchdog, yaml' >/dev/null 2>&1; then
  echo "[setup] Installing Python dependencies"
  "$PYTHON_BIN" -m pip install --quiet -r "$ROOT_DIR/kanban/requirements.txt"
fi

if [[ ! -d "$ROOT_DIR/canvas-studio/node_modules" ]]; then
  echo "[setup] Installing Canvas Studio dependencies"
  (cd "$ROOT_DIR/canvas-studio" && npm ci --no-audit --no-fund)
fi

echo "[setup] Building Canvas Studio"
(cd "$ROOT_DIR/canvas-studio" && npm run build)

export KANBAN_REPO_ROOT="$ROOT_DIR"
if [[ -z "${KANBAN_CONFIG:-}" ]]; then
  if [[ -f "$ROOT_DIR/.kanban.config.json" ]]; then
    export KANBAN_CONFIG="$ROOT_DIR/.kanban.config.json"
  else
    export KANBAN_CONFIG="$ROOT_DIR/demo/kanban.demo.config.json"
  fi
fi

DEMO_URL="http://localhost:$PORT/canvas/?path=demo%2Fprojects%2Fliterature-review%2FDEMO-001.md"
echo "[start] Demo: $DEMO_URL"

probe_port_state() {
  "$PYTHON_BIN" - "$PORT" <<'PY'
import http.client
import json
import socket
import sys

port = int(sys.argv[1])
try:
    with socket.create_connection(("127.0.0.1", port), timeout=0.25):
        pass
except OSError:
    print("free")
    raise SystemExit(0)

connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.75)
try:
    connection.request("GET", "/api/health", headers={"Host": f"127.0.0.1:{port}"})
    response = connection.getresponse()
    payload = json.loads(response.read(16384).decode("utf-8")) if response.status == 200 else {}
    if (payload.get("product") == "project-canvas"
            and payload.get("fingerprint") == "project-canvas/health-v1"):
        print("match")
    else:
        print("occupied")
except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
    print("occupied")
finally:
    connection.close()
PY
}

open_demo_url() {
  [[ "$OPEN_BROWSER" == "1" ]] || return 0
  case "$PLATFORM_NAME" in
    Darwin)
      if command -v open >/dev/null 2>&1; then
        open "$DEMO_URL" >/dev/null 2>&1 || echo "[platform] Browser auto-open failed; open $DEMO_URL manually" >&2
      else
        echo "[platform] macOS open command unavailable; open $DEMO_URL manually" >&2
      fi
      ;;
    Linux)
      if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$DEMO_URL" >/dev/null 2>&1 || echo "[platform] Browser auto-open failed; open $DEMO_URL manually" >&2
      else
        echo "[platform] xdg-open unavailable; open $DEMO_URL manually" >&2
      fi
      ;;
    *)
      echo "[platform] Browser auto-open is unavailable on $PLATFORM_NAME; open $DEMO_URL manually" >&2
      ;;
  esac
}

PORT_STATE="$(probe_port_state)"
if [[ "$PORT_STATE" == "match" ]]; then
  echo "[ready] Existing Project Canvas instance verified; reusing port $PORT"
  open_demo_url
  exit 0
fi
if [[ "$PORT_STATE" != "free" ]]; then
  echo "Port $PORT is occupied by another service; expected health fingerprint project-canvas/health-v1. Refusing to reuse it." >&2
  exit 1
fi

"$PYTHON_BIN" "$ROOT_DIR/kanban/scan-docs.py" --serve --port "$PORT" &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

READY="0"
for ((_attempt = 1; _attempt <= 120; _attempt++)); do
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    wait "$SERVER_PID"
    exit $?
  fi
  if [[ "$(probe_port_state)" == "match" ]]; then
    READY="1"
    break
  fi
  sleep 0.25
done

if [[ "$READY" != "1" ]]; then
  echo "Server did not become ready on port $PORT" >&2
  exit 1
fi

echo "[ready] Kanban and demo canvas are available"
open_demo_url

wait "$SERVER_PID"
