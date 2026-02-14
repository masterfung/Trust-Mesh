#!/usr/bin/env bash
# TrustMesh dev environment — start, stop, and manage backend + frontend.
#
# Usage:
#   ./dev.sh start    # Seed DB + start backend (8000) + frontend (3050)
#   ./dev.sh stop     # Stop both processes cleanly
#   ./dev.sh restart  # Stop then start
#   ./dev.sh status   # Show running processes
#   ./dev.sh logs     # Tail both log files
#   ./dev.sh seed     # Re-seed the database (auto-snapshots)
#   ./dev.sh snapshot # Save current DB as snapshot
#   ./dev.sh restore  # Restore DB from snapshot

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT/trustmesh-core"
FRONTEND_DIR="$ROOT/trustmesh-ui"
BACKEND_PID="$ROOT/.backend.pid"
FRONTEND_PID="$ROOT/.frontend.pid"
BACKEND_LOG="$ROOT/.backend.log"
FRONTEND_LOG="$ROOT/.frontend.log"
BACKEND_PORT=8000
FRONTEND_PORT=3050

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
  echo ""
  echo "  Logs: ./dev.sh logs"
  echo "  Stop: ./dev.sh stop"
}

cmd_stop() {
  _kill_pid "$FRONTEND_PID" "frontend"
  _kill_pid "$BACKEND_PID" "backend"
  # Clean up any orphans on our ports
  _kill_port $BACKEND_PORT
  _kill_port $FRONTEND_PORT
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
}

cmd_logs() {
  echo "=== Tailing backend + frontend logs (Ctrl+C to stop) ==="
  tail -f "$BACKEND_LOG" "$FRONTEND_LOG" 2>/dev/null || echo "No log files found. Start the app first."
}

# ── Main ──

case "${1:-start}" in
  start)    cmd_start    ;;
  stop)     cmd_stop     ;;
  restart)  cmd_restart  ;;
  status)   cmd_status   ;;
  logs)     cmd_logs     ;;
  seed)     cmd_seed     ;;
  snapshot) cmd_snapshot ;;
  restore)  cmd_restore  ;;
  *)
    echo "Usage: ./dev.sh {start|stop|restart|status|logs|seed|snapshot|restore}"
    exit 1
    ;;
esac
