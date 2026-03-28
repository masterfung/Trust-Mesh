#!/usr/bin/env bash
# demo-3pod.sh — simplified 3-pod local demo launcher
#
# Usage:
#   ./demo-3pod.sh seed    — seed databases for family / hospital / work pods
#   ./demo-3pod.sh start   — start all 3 pods + frontend
#   ./demo-3pod.sh wire    — wire pods together via federation API
#   ./demo-3pod.sh stop    — stop all
#   ./demo-3pod.sh status  — show running pods

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$SCRIPT_DIR/trustmesh-core"
UI="$SCRIPT_DIR/trustmesh-ui"
LOG_DIR="$SCRIPT_DIR/logs/demo-3pod"
DATA_DIR="$SCRIPT_DIR/data/demo"

FAMILY_PORT=9000
HOSPITAL_PORT=9001
WORK_PORT=9002
FRONTEND_PORT=3050

FAMILY_URL="http://localhost:$FAMILY_PORT"
HOSPITAL_URL="http://localhost:$HOSPITAL_PORT"
WORK_URL="http://localhost:$WORK_PORT"

cmd="${1:-help}"

# ── helpers ──────────────────────────────────────────────────────────────────

log() { echo "[demo-3pod] $*"; }

wait_healthy() {
    local url="$1" name="$2" max="${3:-30}"
    log "Waiting for $name ($url)..."
    for i in $(seq 1 "$max"); do
        if curl -sf "$url/health" >/dev/null 2>&1; then
            log "$name is up"
            return 0
        fi
        sleep 1
    done
    log "WARNING: $name did not become healthy in ${max}s"
    return 1
}

# ── commands ──────────────────────────────────────────────────────────────────

cmd_seed() {
    log "Seeding databases..."
    mkdir -p "$LOG_DIR" "$DATA_DIR/family" "$DATA_DIR/hospital" "$DATA_DIR/work"

    for pod in family hospital work; do
        log "  Seeding $pod pod..."
        TRUSTMESH_DB="$DATA_DIR/$pod/trustmesh.db" \
        TRUSTMESH_POD_NAME="$pod" \
            uv --directory "$CORE" run python -m src.seed \
            > "$LOG_DIR/${pod}-seed.log" 2>&1 \
            && log "  ✓ $pod seeded" \
            || { log "  ✗ $pod seed failed (see $LOG_DIR/${pod}-seed.log)"; exit 1; }
    done
    log "All pods seeded."
}

cmd_start() {
    mkdir -p "$LOG_DIR"
    log "Starting pods..."

    # Family pod (port 9000)
    TRUSTMESH_DB="$DATA_DIR/family/trustmesh.db" \
    TRUSTMESH_POD_NAME="family" \
    TRUSTMESH_POD_URL="$FAMILY_URL" \
        uv --directory "$CORE" run uvicorn src.main:app \
        --host 127.0.0.1 --port "$FAMILY_PORT" \
        > "$LOG_DIR/family.log" 2>&1 &
    echo $! > "$LOG_DIR/family.pid"
    log "Family pod started (pid $!)"

    # Hospital pod (port 9001)
    TRUSTMESH_DB="$DATA_DIR/hospital/trustmesh.db" \
    TRUSTMESH_POD_NAME="hospital" \
    TRUSTMESH_POD_URL="$HOSPITAL_URL" \
        uv --directory "$CORE" run uvicorn src.main:app \
        --host 127.0.0.1 --port "$HOSPITAL_PORT" \
        > "$LOG_DIR/hospital.log" 2>&1 &
    echo $! > "$LOG_DIR/hospital.pid"
    log "Hospital pod started (pid $!)"

    # Work pod (port 9002)
    TRUSTMESH_DB="$DATA_DIR/work/trustmesh.db" \
    TRUSTMESH_POD_NAME="work" \
    TRUSTMESH_POD_URL="$WORK_URL" \
        uv --directory "$CORE" run uvicorn src.main:app \
        --host 127.0.0.1 --port "$WORK_PORT" \
        > "$LOG_DIR/work.log" 2>&1 &
    echo $! > "$LOG_DIR/work.pid"
    log "Work pod started (pid $!)"

    # Frontend (port 3050, pointing at family pod)
    ( cd "$UI" && NEXT_PUBLIC_API_URL="$FAMILY_URL" bun run dev ) \
        > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$LOG_DIR/frontend.pid"
    log "Frontend started (pid $!)"

    log ""
    log "Services:"
    log "  Family pod:   $FAMILY_URL"
    log "  Hospital pod: $HOSPITAL_URL"
    log "  Work pod:     $WORK_URL"
    log "  Frontend:     http://localhost:$FRONTEND_PORT"
    log ""
    log "Waiting for pods to become healthy..."
    wait_healthy "$FAMILY_URL" "family" 30 || true
    wait_healthy "$HOSPITAL_URL" "hospital" 30 || true
    wait_healthy "$WORK_URL" "work" 30 || true
}

cmd_wire() {
    log "Wiring pods together via federation API..."

    # Each pod has its own primary user (pod-scoped seeding means molly is only on family).
    FAMILY_USER="molly"
    HOSPITAL_USER="dr_lee"
    WORK_USER="kyle"
    DEMO_PASS="TrustMesh-demo-2026"

    # Helper: POST with session cookie (uses temp cookie file — curl -c - mixes stdout)
    # Usage: post_with_auth <pod_url> <username> <path> <body>
    post_with_auth() {
        local pod_url="$1" username="$2" path="$3" body="$4"
        local cookie_file
        cookie_file=$(mktemp /tmp/tm_cookie.XXXXXX)

        local http_code
        http_code=$(curl -s -w "%{http_code}" -o /dev/null \
            -c "$cookie_file" \
            -X POST "$pod_url/api/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"username\":\"$username\",\"password\":\"$DEMO_PASS\"}")

        if [ "$http_code" != "200" ]; then
            log "WARNING: Could not authenticate $username with $pod_url (HTTP $http_code)"
            rm -f "$cookie_file"
            return 1
        fi

        curl -s -X POST "$pod_url$path" \
            -H "Content-Type: application/json" \
            -b "$cookie_file" \
            -d "$body" || true
        rm -f "$cookie_file"
    }

    # Wire all 6 directed connections (each pod must know about the other two)
    log "  family → hospital"
    post_with_auth "$FAMILY_URL" "$FAMILY_USER" "/api/pod/peers" \
        "{\"url\":\"$HOSPITAL_URL\",\"name\":\"hospital\"}" | head -c 200
    echo ""

    log "  family → work"
    post_with_auth "$FAMILY_URL" "$FAMILY_USER" "/api/pod/peers" \
        "{\"url\":\"$WORK_URL\",\"name\":\"work\"}" | head -c 200
    echo ""

    log "  hospital → family"
    post_with_auth "$HOSPITAL_URL" "$HOSPITAL_USER" "/api/pod/peers" \
        "{\"url\":\"$FAMILY_URL\",\"name\":\"family\"}" | head -c 200
    echo ""

    log "  hospital → work"
    post_with_auth "$HOSPITAL_URL" "$HOSPITAL_USER" "/api/pod/peers" \
        "{\"url\":\"$WORK_URL\",\"name\":\"work\"}" | head -c 200
    echo ""

    log "  work → family"
    post_with_auth "$WORK_URL" "$WORK_USER" "/api/pod/peers" \
        "{\"url\":\"$FAMILY_URL\",\"name\":\"family\"}" | head -c 200
    echo ""

    log "  work → hospital"
    post_with_auth "$WORK_URL" "$WORK_USER" "/api/pod/peers" \
        "{\"url\":\"$HOSPITAL_URL\",\"name\":\"hospital\"}" | head -c 200
    echo ""

    log "Pods wired. Cross-pod queries now possible."
    log ""
    log "Demo:"
    log "  1. Open http://localhost:$FRONTEND_PORT"
    log "  2. Login as molly / TrustMesh-demo-2026"
    log "  3. Open Live Agent → ask: 'What does Dr. Lee know about Rose?'"
    log "  4. Wait ~5 min for Timeline to fire → proactive conflict inject"
    log "  5. Login as grandmarose → say 'I've been in an accident'"
}

cmd_stop() {
    log "Stopping all pods..."
    for svc in family hospital work frontend; do
        pid_file="$LOG_DIR/${svc}.pid"
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            if kill "$pid" 2>/dev/null; then
                log "  Stopped $svc (pid $pid)"
            fi
            rm -f "$pid_file"
        fi
    done
    log "Done."
}

cmd_status() {
    log "Pod status:"
    for pod_url in "$FAMILY_URL" "$HOSPITAL_URL" "$WORK_URL"; do
        if curl -sf "$pod_url/health" >/dev/null 2>&1; then
            echo "  ✓ $pod_url"
        else
            echo "  ✗ $pod_url (unreachable)"
        fi
    done
}

# ── dispatch ──────────────────────────────────────────────────────────────────

case "$cmd" in
    seed)    cmd_seed ;;
    start)   cmd_start ;;
    wire)    cmd_wire ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    *)
        echo "Usage: $0 {seed|start|wire|stop|status}"
        echo ""
        echo "  seed    Seed databases for all 3 pods"
        echo "  start   Start all 3 pods + frontend"
        echo "  wire    Wire pods together via federation"
        echo "  stop    Stop all processes"
        echo "  status  Check pod health"
        exit 1
        ;;
esac
