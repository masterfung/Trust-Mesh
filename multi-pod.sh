#!/opt/homebrew/bin/bash
# TrustMesh Multi-Pod Federation — launch 19 pods + registry + frontend.
#
# Requires: Bash 4.0+ (for associative arrays).
#   macOS ships with Bash 3.2 — install a newer version:
#     brew install bash
#   Then either run explicitly: /opt/homebrew/bin/bash multi-pod.sh demo
#   Or add /opt/homebrew/bin to your PATH before /bin.
#
# Usage:
#   ./multi-pod.sh seed         # Generate per-pod databases
#   ./multi-pod.sh start        # Start registry + 19 pods + frontend
#   ./multi-pod.sh orchestrate  # Wire peers, pools, ghost users
#   ./multi-pod.sh status       # Show pod health
#   ./multi-pod.sh stop         # Stop everything
#   ./multi-pod.sh demo         # seed + start + orchestrate (full setup)

set -euo pipefail

# Require Bash 4+ for associative arrays
if ((BASH_VERSINFO[0] < 4)); then
  echo "ERROR: Bash 4.0+ required (found ${BASH_VERSION})."
  echo "  macOS fix: brew install bash && /opt/homebrew/bin/bash $0 $*"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT/trustmesh-core"
FRONTEND_DIR="$ROOT/trustmesh-ui"
REGISTRY_DIR="$ROOT/trustmesh-registry"
DATA_DIR="$BACKEND_DIR/data/pods"
LOG_DIR="$ROOT/.multipod-logs"
PID_DIR="$ROOT/.multipod-pids"

REGISTRY_PORT=8100
FRONTEND_PORT=3050

# Federation shared secret (generated once per session, shared by all pods + orchestrator)
POOL_SYNC_SECRET_FILE="$ROOT/.multipod-secret"

# Pod definitions: key port
PODS=(
  "sarah:8001"
  "mike:8002"
  "emma:8003"
  "grandma:8004"
  "dr_chen:8005"
  "tom:8006"
  "lisa:8007"
  "priya:8008"
  "james:8009"
  "maria:8010"
  "techcorp:8011"
  "hospital:8012"
  "music:8013"
  "city:8014"
  "insurance:8015"
  "dance:8016"
)

# Display names for status output
declare -A POD_NAMES=(
  [sarah]="Sarah Johnson"
  [mike]="Mike Johnson"
  [emma]="Emma Johnson"
  [grandma]="Grandma Rose"
  [dr_chen]="Dr. Chen"
  [tom]="Tom (Plumber)"
  [lisa]="Lisa Rodriguez"
  [priya]="Priya Patel"
  [james]="James Wilson"
  [maria]="Maria Santos"
  [techcorp]="TechCorp"
  [hospital]="Riverside Hospital"
  [music]="Music Collective"
  [city]="City of Riverside"
  [insurance]="Insurance Co"
  [dance]="Dance Studio"
)

# ── Helpers ──

_ensure_dirs() {
  mkdir -p "$LOG_DIR" "$PID_DIR"
}

_ensure_secret() {
  if [[ ! -f "$POOL_SYNC_SECRET_FILE" ]]; then
    openssl rand -hex 32 > "$POOL_SYNC_SECRET_FILE"
    chmod 600 "$POOL_SYNC_SECRET_FILE"
  fi
  TRUSTMESH_POOL_SYNC_SECRET=$(<"$POOL_SYNC_SECRET_FILE")
  export TRUSTMESH_POOL_SYNC_SECRET
}

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
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 6); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$pidfile"
  fi
}

_kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

_wait_for_health() {
  local url="$1" max_wait="${2:-20}"
  for _ in $(seq 1 "$max_wait"); do
    if curl -sf "$url" > /dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

# ── Commands ──

cmd_seed() {
  echo ""
  echo "=== Seeding 19 pod databases ==="
  echo ""
  cd "$BACKEND_DIR"
  uv run python -m src.seed_multi

  # Reset registry if it's running
  if curl -sf "http://localhost:$REGISTRY_PORT/api/health" > /dev/null 2>&1; then
    echo ""
    echo "Resetting registry..."
    curl -sf -X POST "http://localhost:$REGISTRY_PORT/api/reset" > /dev/null 2>&1 || true
  fi
}

cmd_start() {
  _ensure_dirs
  _ensure_secret

  echo ""
  echo "=== Starting TrustMesh Multi-Pod Federation ==="
  echo ""

  # 1. Start public registry (Next.js)
  echo "Starting registry on :$REGISTRY_PORT..."
  _kill_port $REGISTRY_PORT
  cd "$REGISTRY_DIR"
  nohup bun dev --port $REGISTRY_PORT > "$LOG_DIR/registry.log" 2>&1 &
  echo $! > "$PID_DIR/registry.pid"

  # 2. Start 19 pods
  cd "$BACKEND_DIR"
  for entry in "${PODS[@]}"; do
    local key="${entry%%:*}"
    local port="${entry##*:}"
    local db_path="$DATA_DIR/${key}.db"

    if [[ ! -f "$db_path" ]]; then
      echo "  SKIP :{$port} $key — no database (run: ./multi-pod.sh seed)"
      continue
    fi

    _kill_port "$port"

    # Each pod gets its own env vars
    TRUSTMESH_POD_NAME="${POD_NAMES[$key]:-$key}" \
    TRUSTMESH_POD_URL="http://localhost:${port}" \
    TRUSTMESH_DB="$db_path" \
    TRUSTMESH_POOL_SYNC_SECRET="$TRUSTMESH_POOL_SYNC_SECRET" \
    TRUSTMESH_REGISTRY_URL="http://localhost:${REGISTRY_PORT}" \
    nohup uv run uvicorn src.main:app --port "$port" > "$LOG_DIR/${key}.log" 2>&1 &
    echo $! > "$PID_DIR/${key}.pid"
    echo "  Started :${port}  ${POD_NAMES[$key]:-$key}"
  done

  # 3. Start frontend
  echo ""
  echo "Starting frontend on :$FRONTEND_PORT..."
  _kill_port $FRONTEND_PORT
  cd "$FRONTEND_DIR"
  nohup bun dev --port $FRONTEND_PORT > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"

  # 4. Wait for registry + a sample pod
  echo ""
  echo -n "Waiting for services..."
  if _wait_for_health "http://localhost:$REGISTRY_PORT/api/health" 20; then
    echo -n " registry"
  fi
  if _wait_for_health "http://localhost:8001/health" 30; then
    echo -n " pods"
  fi
  if _wait_for_health "http://localhost:$FRONTEND_PORT" 20; then
    echo -n " frontend"
  fi
  echo " ready."

  echo ""
  echo "=== Multi-Pod Federation Running ==="
  echo ""
  echo "  Registry:  http://localhost:$REGISTRY_PORT"
  echo "  Pods:      http://localhost:8001 - http://localhost:8016"
  echo "  Frontend:  http://localhost:$FRONTEND_PORT"
  echo ""
  echo "  Next: ./multi-pod.sh orchestrate"
  echo "  Stop: ./multi-pod.sh stop"
  echo ""
}

cmd_orchestrate() {
  _ensure_secret
  echo ""
  echo "=== Orchestrating federation ==="
  echo ""
  cd "$BACKEND_DIR"
  TRUSTMESH_POOL_SYNC_SECRET="$TRUSTMESH_POOL_SYNC_SECRET" uv run python orchestrate.py
}

cmd_stop() {
  echo ""
  echo "=== Stopping Multi-Pod Federation ==="
  echo ""

  # Stop frontend
  _kill_pid "$PID_DIR/frontend.pid" "frontend"
  _kill_port $FRONTEND_PORT

  # Stop all pods
  for entry in "${PODS[@]}"; do
    local key="${entry%%:*}"
    local port="${entry##*:}"
    _kill_pid "$PID_DIR/${key}.pid" "$key"
    _kill_port "$port"
  done

  # Stop registry
  _kill_pid "$PID_DIR/registry.pid" "registry"
  _kill_port $REGISTRY_PORT

  # Clean up secret
  rm -f "$POOL_SYNC_SECRET_FILE"

  echo "All services stopped."
  echo ""
}

cmd_status() {
  echo ""
  echo "=== Multi-Pod Federation Status ==="
  echo ""

  # Registry
  if curl -sf "http://localhost:$REGISTRY_PORT/api/health" > /dev/null 2>&1; then
    local count
    count=$(curl -sf "http://localhost:$REGISTRY_PORT/api/health" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('agent_count',0))" 2>/dev/null || echo "?")
    printf "  %-8s %-25s %s\n" ":$REGISTRY_PORT" "Registry" "ONLINE ($count agents)"
  else
    printf "  %-8s %-25s %s\n" ":$REGISTRY_PORT" "Registry" "OFFLINE"
  fi

  # Pods
  local online=0 total=0
  for entry in "${PODS[@]}"; do
    local key="${entry%%:*}"
    local port="${entry##*:}"
    total=$((total + 1))

    if curl -sf "http://localhost:${port}/health" > /dev/null 2>&1; then
      online=$((online + 1))
      printf "  %-8s %-25s %s\n" ":${port}" "${POD_NAMES[$key]:-$key}" "ONLINE"
    else
      printf "  %-8s %-25s %s\n" ":${port}" "${POD_NAMES[$key]:-$key}" "OFFLINE"
    fi
  done

  # Frontend
  if curl -sf "http://localhost:$FRONTEND_PORT" > /dev/null 2>&1; then
    printf "  %-8s %-25s %s\n" ":$FRONTEND_PORT" "Frontend" "ONLINE"
  else
    printf "  %-8s %-25s %s\n" ":$FRONTEND_PORT" "Frontend" "OFFLINE"
  fi

  echo ""
  echo "  $online/$total pods online"
  echo ""
}

cmd_logs() {
  echo "=== Tailing all logs (Ctrl+C to stop) ==="
  tail -f "$LOG_DIR"/*.log 2>/dev/null || echo "No logs found. Run: ./multi-pod.sh start"
}

cmd_demo() {
  cmd_seed
  cmd_start
  # Give pods extra time to init
  echo "Waiting for pods to initialize..."
  sleep 5
  cmd_orchestrate
  cmd_status
}

# ── Main ──

case "${1:-status}" in
  seed)         cmd_seed        ;;
  start)        cmd_start       ;;
  orchestrate)  cmd_orchestrate ;;
  stop)         cmd_stop        ;;
  status)       cmd_status      ;;
  logs)         cmd_logs        ;;
  demo)         cmd_demo        ;;
  *)
    echo "Usage: ./multi-pod.sh {seed|start|orchestrate|stop|status|logs|demo}"
    exit 1
    ;;
esac
