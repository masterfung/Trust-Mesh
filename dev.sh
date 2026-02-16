#!/usr/bin/env bash
# TrustMesh dev environment — start, stop, and manage backend + frontend + Citadel.
#
# Usage:
#   ./dev.sh start    # Seed DB + start backend (8000) + frontend (3050)
#   ./dev.sh stop     # Stop all processes cleanly
#   ./dev.sh restart  # Stop then start
#   ./dev.sh status   # Show running processes
#   ./dev.sh logs     # Tail all log files
#   ./dev.sh seed     # Re-seed the database (auto-snapshots)
#   ./dev.sh snapshot # Save current DB as snapshot
#   ./dev.sh restore  # Restore DB from snapshot
#   ./dev.sh citadel  # Setup + start Citadel sidecar only

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT/trustmesh-core"
FRONTEND_DIR="$ROOT/trustmesh-ui"
CITADEL_DIR="$ROOT/citadel-ref"
BACKEND_PID="$ROOT/.backend.pid"
FRONTEND_PID="$ROOT/.frontend.pid"
CITADEL_PID="$ROOT/.citadel.pid"
BACKEND_LOG="$ROOT/.backend.log"
FRONTEND_LOG="$ROOT/.frontend.log"
CITADEL_LOG="$ROOT/.citadel.log"
BACKEND_PORT=8000
FRONTEND_PORT=3050
CITADEL_PORT=3001

# ── Helpers ──

_is_running() {
  local pidfile="$1"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(<"$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$pidfile"
  fi
  return 1
}

_kill_pid() {
  local pidfile="$1" name="$2"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(<"$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping $name (PID $pid)..."
      kill "$pid" 2>/dev/null || true
      # Wait up to 5 seconds for clean exit
      for _ in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      # Force kill if still running
      if kill -0 "$pid" 2>/dev/null; then
        echo "  Force killing $name..."
        kill -9 "$pid" 2>/dev/null || true
      fi
      echo "  $name stopped."
    fi
    rm -f "$pidfile"
  fi
}

_kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "Killing leftover processes on port $port..."
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

# ── Commands ──

cmd_seed() {
  echo "Seeding database..."
  cd "$BACKEND_DIR"
  uv run python -m src.seed
  if [[ -f "$BACKEND_DIR/trustmesh.db" ]]; then
    cp "$BACKEND_DIR/trustmesh.db" "$BACKEND_DIR/trustmesh.db.snapshot"
    echo "Snapshot saved: trustmesh.db.snapshot"
  fi
  echo "Seed complete."
}

cmd_snapshot() {
  if [[ -f "$BACKEND_DIR/trustmesh.db" ]]; then
    cp "$BACKEND_DIR/trustmesh.db" "$BACKEND_DIR/trustmesh.db.snapshot"
    echo "Snapshot saved: trustmesh.db.snapshot"
  else
    echo "No database to snapshot. Run ./dev.sh seed first."
  fi
}

cmd_restore() {
  if [[ -f "$BACKEND_DIR/trustmesh.db.snapshot" ]]; then
    cp "$BACKEND_DIR/trustmesh.db.snapshot" "$BACKEND_DIR/trustmesh.db"
    echo "Database restored from snapshot."
  else
    echo "No snapshot found. Run ./dev.sh snapshot first."
  fi
}

cmd_citadel_setup() {
  # Build Citadel with ML support if not already built
  if [[ ! -d "$CITADEL_DIR" ]]; then
    echo "Citadel directory not found at $CITADEL_DIR"
    echo "Clone it: git clone https://github.com/TryMightyAI/citadel.git citadel-ref"
    return 1
  fi

  local citadel_bin="$CITADEL_DIR/citadel"

  # Check if ML model exists
  if [[ ! -f "$CITADEL_DIR/models/modernbert-base/model.onnx" ]]; then
    echo "ML model not found. Running setup-ml.sh..."
    cd "$CITADEL_DIR"
    ./scripts/setup-ml.sh
    cd "$ROOT"
  fi

  # Build with ML support if binary missing or older than source
  if [[ ! -f "$citadel_bin" ]] || [[ "$CITADEL_DIR/cmd/gateway/main.go" -nt "$citadel_bin" ]]; then
    echo "Building Citadel with ML detection..."
    cd "$CITADEL_DIR"
    make build-ml
    cd "$ROOT"
  fi

  echo "Citadel ready."
}

cmd_citadel_start() {
  if _is_running "$CITADEL_PID"; then
    echo "Citadel is already running."
    return 0
  fi

  local citadel_bin="$CITADEL_DIR/citadel"
  if [[ ! -f "$citadel_bin" ]]; then
    echo "Citadel binary not found. Run: ./dev.sh citadel"
    return 1
  fi

  _kill_port $CITADEL_PORT

  echo "Starting Citadel sidecar on :$CITADEL_PORT..."

  # Set up env for ML model
  local platform arch onnx_lib tok_lib
  platform=$(uname -s | tr '[:upper:]' '[:lower:]')
  arch=$(uname -m)
  if [[ "$platform" == "darwin" ]]; then
    if [[ "$arch" == "arm64" ]]; then
      onnx_lib="$HOME/onnxruntime-osx-arm64-1.23.2/lib"
    else
      onnx_lib="$HOME/onnxruntime-osx-x64-1.23.2/lib"
    fi
    tok_lib="$HOME/tokenizers"
    export DYLD_LIBRARY_PATH="${onnx_lib}:${DYLD_LIBRARY_PATH:-}"
  else
    if [[ "$arch" == "aarch64" ]]; then
      onnx_lib="$HOME/onnxruntime-linux-aarch64-1.23.2/lib"
    else
      onnx_lib="$HOME/onnxruntime-linux-x64-1.23.2/lib"
    fi
    tok_lib="/usr/local/lib"
    export LD_LIBRARY_PATH="${onnx_lib}:${LD_LIBRARY_PATH:-}"
  fi

  export HUGOT_MODEL_PATH="$CITADEL_DIR/models/modernbert-base"
  export CITADEL_ENABLE_HUGOT=true

  nohup "$citadel_bin" serve $CITADEL_PORT > "$CITADEL_LOG" 2>&1 &
  echo $! > "$CITADEL_PID"

  echo -n "  Waiting for Citadel"
  for _ in $(seq 1 15); do
    if curl -sf http://localhost:$CITADEL_PORT/health > /dev/null 2>&1; then
      echo " ready."
      return 0
    fi
    echo -n "."
    sleep 0.5
  done
  echo " (may still be loading ML model)"
}

cmd_start() {
  # Check if already running
  if _is_running "$BACKEND_PID" && _is_running "$FRONTEND_PID"; then
    echo "TrustMesh is already running."
    cmd_status
    return 0
  fi

  # Clean up stale port bindings
  _kill_port $BACKEND_PORT
  _kill_port $FRONTEND_PORT

  # Seed if no database
  if [[ ! -f "$BACKEND_DIR/trustmesh.db" ]]; then
    cmd_seed
  fi

  # Auto-setup + start Citadel sidecar if citadel-ref/ exists
  if [[ -d "$CITADEL_DIR" ]]; then
    if [[ ! -f "$CITADEL_DIR/citadel" ]]; then
      echo "Citadel repo found — building automatically (first time may download ~685MB model)..."
      cmd_citadel_setup || echo "  Citadel build failed — continuing with heuristic fallback."
    fi
    if [[ -f "$CITADEL_DIR/citadel" ]]; then
      cmd_citadel_start
      export CITADEL_URL="http://localhost:$CITADEL_PORT"
    fi
  fi

  # Start backend
  echo "Starting backend on :$BACKEND_PORT..."
  cd "$BACKEND_DIR"
  nohup uv run uvicorn src.main:app --reload --port $BACKEND_PORT > "$BACKEND_LOG" 2>&1 &
  echo $! > "$BACKEND_PID"

  # Wait for backend health
  echo -n "  Waiting for backend"
  for _ in $(seq 1 20); do
    if curl -sf http://localhost:$BACKEND_PORT/health/full > /dev/null 2>&1; then
      echo " ready."
      break
    fi
    echo -n "."
    sleep 0.5
  done

  # Start frontend
  echo "Starting frontend on :$FRONTEND_PORT..."
  cd "$FRONTEND_DIR"
  nohup bun dev --port $FRONTEND_PORT > "$FRONTEND_LOG" 2>&1 &
  echo $! > "$FRONTEND_PID"

  # Wait for frontend
  echo -n "  Waiting for frontend"
  for _ in $(seq 1 20); do
    if curl -sf http://localhost:$FRONTEND_PORT > /dev/null 2>&1; then
      echo " ready."
      break
    fi
    echo -n "."
    sleep 0.5
  done

  echo ""
  echo "TrustMesh is running:"
  echo "  Backend:  http://localhost:$BACKEND_PORT"
  echo "  Frontend: http://localhost:$FRONTEND_PORT"
  if _is_running "$CITADEL_PID"; then
    echo "  Citadel:  http://localhost:$CITADEL_PORT (ML security scanning)"
  fi
  echo ""
  echo "  Logs: ./dev.sh logs"
  echo "  Stop: ./dev.sh stop"
}

cmd_stop() {
  _kill_pid "$FRONTEND_PID" "frontend"
  _kill_pid "$BACKEND_PID" "backend"
  _kill_pid "$CITADEL_PID" "citadel"
  # Clean up any orphans on our ports
  _kill_port $BACKEND_PORT
  _kill_port $FRONTEND_PORT
  _kill_port $CITADEL_PORT
  echo "TrustMesh stopped."
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

cmd_status() {
  echo "TrustMesh Status:"
  if _is_running "$BACKEND_PID"; then
    echo "  Backend:  RUNNING (PID $(<"$BACKEND_PID"), port $BACKEND_PORT)"
  else
    echo "  Backend:  STOPPED"
  fi
  if _is_running "$FRONTEND_PID"; then
    echo "  Frontend: RUNNING (PID $(<"$FRONTEND_PID"), port $FRONTEND_PORT)"
  else
    echo "  Frontend: STOPPED"
  fi
  if _is_running "$CITADEL_PID"; then
    echo "  Citadel:  RUNNING (PID $(<"$CITADEL_PID"), port $CITADEL_PORT)"
  else
    echo "  Citadel:  STOPPED"
  fi
}

cmd_logs() {
  echo "=== Tailing backend + frontend + citadel logs (Ctrl+C to stop) ==="
  tail -f "$BACKEND_LOG" "$FRONTEND_LOG" "$CITADEL_LOG" 2>/dev/null || echo "No log files found. Start the app first."
}

# ── Main ──

case "${1:-start}" in
  start)    cmd_start         ;;
  stop)     cmd_stop          ;;
  restart)  cmd_restart       ;;
  status)   cmd_status        ;;
  logs)     cmd_logs          ;;
  seed)     cmd_seed          ;;
  snapshot) cmd_snapshot      ;;
  restore)  cmd_restore       ;;
  citadel)  cmd_citadel_setup && cmd_citadel_start ;;
  *)
    echo "Usage: ./dev.sh {start|stop|restart|status|logs|seed|snapshot|restore|citadel}"
    exit 1
    ;;
esac
