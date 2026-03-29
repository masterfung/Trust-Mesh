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
CITADEL_DIR="$ROOT/citadel-ref"
DATA_DIR="$BACKEND_DIR/data/pods"
LOG_DIR="$ROOT/.multipod-logs"
PID_DIR="$ROOT/.multipod-pids"

REGISTRY_PORT=9100
FRONTEND_PORT=3050
CITADEL_PORT=3001

# Federation shared secret (generated once per session, shared by all pods + orchestrator)
POOL_SYNC_SECRET_FILE="$ROOT/.multipod-secret"

# Pod definitions: key:port — keys match seed usernames
PODS=(
  "molly:9001"
  "peter:9002"
  "jane:9003"
  "grandmarose:9004"
  "dr_lee:9005"
  "kyle:9006"
  "amy:9007"
  "dorothy:9008"
  "nurse_davis:9009"
  "emt_johnson:9010"
  "sparkleclean:9011"
  "riverside_hospital:9012"
  "acetutor:9013"
  "riverside_gov:9014"
  "handypro:9015"
  "riverside_ambulance:9016"
)

# Display names for status output
declare -A POD_NAMES=(
  [molly]="Molly Johnson"
  [peter]="Peter Johnson"
  [jane]="Jane Johnson"
  [grandmarose]="Grandma Rose"
  [dr_lee]="Dr. Sarah Lee"
  [kyle]="Kyle Rivera"
  [amy]="Amy Torres"
  [dorothy]="Dorothy Park"
  [nurse_davis]="Nurse Rachel Davis"
  [emt_johnson]="EMT Mike Johnson"
  [sparkleclean]="SparkleClean Residential"
  [riverside_hospital]="Riverside Hospital"
  [acetutor]="AceTutor SAT Prep"
  [riverside_gov]="City of Riverside"
  [handypro]="HandyPro Home Services"
  [riverside_ambulance]="Riverside Ambulance"
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

# ── Citadel ──

_citadel_setup() {
  if [[ ! -d "$CITADEL_DIR" ]]; then
    return 1
  fi
  # Download ML model if missing
  if [[ ! -f "$CITADEL_DIR/models/modernbert-base/model.onnx" ]]; then
    echo "Citadel: downloading ML model (~685MB, first time only)..."
    cd "$CITADEL_DIR"
    ./scripts/setup-ml.sh
    cd "$ROOT"
  fi
  # Build binary if missing or outdated
  if [[ ! -f "$CITADEL_DIR/citadel" ]] || [[ "$CITADEL_DIR/cmd/gateway/main.go" -nt "$CITADEL_DIR/citadel" ]]; then
    echo "Citadel: building with ML detection..."
    cd "$CITADEL_DIR"
    make build-ml
    cd "$ROOT"
  fi
}

_citadel_start() {
  local citadel_bin="$CITADEL_DIR/citadel"
  if [[ ! -f "$citadel_bin" ]]; then
    return 1
  fi
  if _is_running "$PID_DIR/citadel.pid"; then
    return 0
  fi
  _kill_port $CITADEL_PORT

  # Platform-specific ONNX Runtime paths
  local platform arch onnx_lib
  platform=$(uname -s | tr '[:upper:]' '[:lower:]')
  arch=$(uname -m)
  if [[ "$platform" == "darwin" ]]; then
    if [[ "$arch" == "arm64" ]]; then
      onnx_lib="$HOME/onnxruntime-osx-arm64-1.23.2/lib"
    else
      onnx_lib="$HOME/onnxruntime-osx-x64-1.23.2/lib"
    fi
    export DYLD_LIBRARY_PATH="${onnx_lib}:${DYLD_LIBRARY_PATH:-}"
  else
    if [[ "$arch" == "aarch64" ]]; then
      onnx_lib="$HOME/onnxruntime-linux-aarch64-1.23.2/lib"
    else
      onnx_lib="$HOME/onnxruntime-linux-x64-1.23.2/lib"
    fi
    export LD_LIBRARY_PATH="${onnx_lib}:${LD_LIBRARY_PATH:-}"
  fi
  export HUGOT_MODEL_PATH="$CITADEL_DIR/models/modernbert-base"
  export CITADEL_ENABLE_HUGOT=true

  nohup "$citadel_bin" serve $CITADEL_PORT > "$LOG_DIR/citadel.log" 2>&1 &
  echo $! > "$PID_DIR/citadel.pid"

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

  # Source .env for API keys, but DON'T overwrite keys already in the
  # shell env (e.g. ANTHROPIC_API_KEY from .zshrc).  We read each line
  # and only export if the var is currently unset or empty.
  if [[ -f "$ROOT/.env" ]]; then
    while IFS='=' read -r key value; do
      # Skip comments and blank lines
      [[ "$key" =~ ^[[:space:]]*# ]] && continue
      [[ -z "$key" ]] && continue
      key="${key%%[[:space:]]}"
      value="${value##[[:space:]]}"
      # Only set if not already in env
      if [[ -z "${!key:-}" ]]; then
        export "$key=$value"
      fi
    done < "$ROOT/.env"
  fi

  # Dev mode: cookies work over HTTP, CSRF secure=false
  export TRUSTMESH_DEV_MODE=1

  echo ""
  echo "=== Starting TrustMesh Multi-Pod Federation ==="
  echo ""

  # 0. Auto-setup + start Citadel sidecar if citadel-ref/ exists
  CITADEL_URL=""
  if [[ -d "$CITADEL_DIR" ]]; then
    _citadel_setup || echo "  Citadel build failed — continuing with heuristic fallback."
    if _citadel_start; then
      CITADEL_URL="http://localhost:$CITADEL_PORT"
      echo "  Citadel ML security: $CITADEL_URL"
    fi
  fi

  # 1. Start public registry (Next.js)
  echo "Starting registry on :$REGISTRY_PORT..."
  _kill_port $REGISTRY_PORT
  cd "$REGISTRY_DIR"
  nohup bun dev --port $REGISTRY_PORT > "$LOG_DIR/registry.log" 2>&1 &
  echo $! > "$PID_DIR/registry.pid"

  # 2a. Start user's own pod on :9000 (fresh DB — no demo users to avoid registry dupes)
  cd "$BACKEND_DIR"
  _kill_port 9000
  TRUSTMESH_POD_NAME="My Pod" \
  TRUSTMESH_POD_URL="http://localhost:9000" \
  TRUSTMESH_FRONTEND_URL="http://localhost:${FRONTEND_PORT}" \
  TRUSTMESH_DB="$DATA_DIR/user.db" \
  TRUSTMESH_POOL_SYNC_SECRET="$TRUSTMESH_POOL_SYNC_SECRET" \
  TRUSTMESH_REGISTRY_URL="http://localhost:${REGISTRY_PORT}" \
  CITADEL_URL="${CITADEL_URL}" \
  nohup uv run uvicorn src.main:app --host '::' --port 9000 > "$LOG_DIR/user.log" 2>&1 &
  echo $! > "$PID_DIR/user.pid"
  echo "  Started :9000  Your Pod (sign up / login here)"

  # 2b. Start 16 demo pods
  for entry in "${PODS[@]}"; do
    local key="${entry%%:*}"
    local port="${entry##*:}"
    local db_path="$DATA_DIR/${key}.db"

    if [[ ! -f "$db_path" ]]; then
      echo "  SKIP :{$port} $key — no database (run: ./multi-pod.sh seed)"
      continue
    fi

    _kill_port "$port"

    # Each pod gets its own env vars (all share one Citadel sidecar)
    TRUSTMESH_POD_NAME="${POD_NAMES[$key]:-$key}" \
    TRUSTMESH_POD_URL="http://localhost:${port}" \
    TRUSTMESH_FRONTEND_URL="http://localhost:${FRONTEND_PORT}" \
    TRUSTMESH_DB="$db_path" \
    TRUSTMESH_POOL_SYNC_SECRET="$TRUSTMESH_POOL_SYNC_SECRET" \
    TRUSTMESH_REGISTRY_URL="http://localhost:${REGISTRY_PORT}" \
    CITADEL_URL="${CITADEL_URL}" \
    nohup uv run uvicorn src.main:app --host '::' --port "$port" > "$LOG_DIR/${key}.log" 2>&1 &
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
  if _wait_for_health "http://localhost:9001/health" 30; then
    echo -n " pods"
  fi
  if _wait_for_health "http://localhost:$FRONTEND_PORT" 20; then
    echo -n " frontend"
  fi
  echo " ready."

  echo ""
  echo "=== Multi-Pod Federation Running ==="
  echo ""
  if [[ -n "$CITADEL_URL" ]]; then
    echo "  Citadel:   $CITADEL_URL (ML security scanning)"
  fi
  echo "  Registry:  http://localhost:$REGISTRY_PORT"
  echo "  Your Pod:  http://localhost:9000  (sign up / login)"
  echo "  Demo Pods: http://localhost:9001 - http://localhost:9016"
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

  # Stop user's own pod
  _kill_pid "$PID_DIR/user.pid" "user pod"
  _kill_port 9000

  # Stop all demo pods
  for entry in "${PODS[@]}"; do
    local key="${entry%%:*}"
    local port="${entry##*:}"
    _kill_pid "$PID_DIR/${key}.pid" "$key"
    _kill_port "$port"
  done

  # Stop registry
  _kill_pid "$PID_DIR/registry.pid" "registry"
  _kill_port $REGISTRY_PORT

  # Stop Citadel
  _kill_pid "$PID_DIR/citadel.pid" "citadel"
  _kill_port $CITADEL_PORT

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

  # User's own pod
  if curl -sf "http://localhost:9000/health" > /dev/null 2>&1; then
    printf "  %-8s %-25s %s\n" ":9000" "Your Pod" "ONLINE"
  else
    printf "  %-8s %-25s %s\n" ":9000" "Your Pod" "OFFLINE"
  fi

  # Demo pods
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

  # Citadel
  if curl -sf "http://localhost:$CITADEL_PORT/health" > /dev/null 2>&1; then
    printf "  %-8s %-25s %s\n" ":$CITADEL_PORT" "Citadel (ML)" "ONLINE"
  else
    printf "  %-8s %-25s %s\n" ":$CITADEL_PORT" "Citadel" "OFFLINE (heuristic fallback)"
  fi

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
