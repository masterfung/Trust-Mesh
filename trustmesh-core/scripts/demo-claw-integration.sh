#!/usr/bin/env bash
# demo-claw-integration.sh — Automated demo of ZeroClaw + TrustMesh integration
#
# Demonstrates: agent memory stored in TrustMesh encrypted vault,
# trust-gated federation between pods, timeline scheduling.
#
# Usage:
#   ./scripts/demo-claw-integration.sh          # Full demo
#   ./scripts/demo-claw-integration.sh setup     # Just setup pods
#   ./scripts/demo-claw-integration.sh teardown  # Just cleanup
#
# Prerequisites:
#   - Zig server built: cd kernel && zig build
#   - Python deps: uv sync
#   - curl available
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Pod config
MOLLY_PORT=8001
DRLEE_PORT=8005
MOLLY_DB="$CORE_DIR/data/demo-molly.db"
DRLEE_DB="$CORE_DIR/data/demo-drlee.db"
DEMO_PASSWORD="DemoPass-2026!"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${BLUE}[demo]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

wait_for_pod() {
    local port=$1 name=$2
    local retries=30
    log "Waiting for $name on :$port..."
    for i in $(seq 1 $retries); do
        if curl -s "http://localhost:$port/api/onboard/status" >/dev/null 2>&1; then
            ok "$name is up"
            return 0
        fi
        sleep 0.5
    done
    fail "$name failed to start on :$port"
}

# ── Setup ──────────────────────────────────────────────────────────

setup() {
    log "Setting up demo pods..."
    mkdir -p "$CORE_DIR/data"

    # Clean old demo DBs
    rm -f "$MOLLY_DB" "$DRLEE_DB"

    # Start Molly's pod (patient)
    log "Starting Molly's pod on :$MOLLY_PORT..."
    TRUSTMESH_DB="$MOLLY_DB" \
    TRUSTMESH_POD_NAME="Molly's Pod" \
    TRUSTMESH_POD_URL="http://localhost:$MOLLY_PORT" \
        "$CORE_DIR/kernel/zig-out/bin/trustmesh-server" --port "$MOLLY_PORT" &
    MOLLY_PID=$!
    echo "$MOLLY_PID" > "$CORE_DIR/data/molly.pid"

    # Start Dr. Lee's pod (doctor)
    log "Starting Dr. Lee's pod on :$DRLEE_PORT..."
    TRUSTMESH_DB="$DRLEE_DB" \
    TRUSTMESH_POD_NAME="Dr. Lee's Pod" \
    TRUSTMESH_POD_URL="http://localhost:$DRLEE_PORT" \
        "$CORE_DIR/kernel/zig-out/bin/trustmesh-server" --port "$DRLEE_PORT" &
    DRLEE_PID=$!
    echo "$DRLEE_PID" > "$CORE_DIR/data/drlee.pid"

    wait_for_pod "$MOLLY_PORT" "Molly"
    wait_for_pod "$DRLEE_PORT" "Dr. Lee"

    # Initialize Molly's pod
    log "Initializing Molly's pod..."
    MOLLY_RESP=$(curl -s -X POST "http://localhost:$MOLLY_PORT/api/onboard/init" \
        -H "Content-Type: application/json" \
        -d "{\"username\": \"molly\", \"password\": \"$DEMO_PASSWORD\", \"display_name\": \"Molly Johnson\", \"user_type\": \"person\"}")
    MOLLY_TOKEN=$(echo "$MOLLY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_token',''))")
    MOLLY_DID=$(echo "$MOLLY_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('did',''))")

    if [ -z "$MOLLY_TOKEN" ]; then
        fail "Failed to initialize Molly's pod: $MOLLY_RESP"
    fi
    ok "Molly initialized: DID=$MOLLY_DID"

    # Initialize Dr. Lee's pod
    log "Initializing Dr. Lee's pod..."
    DRLEE_RESP=$(curl -s -X POST "http://localhost:$DRLEE_PORT/api/onboard/init" \
        -H "Content-Type: application/json" \
        -d "{\"username\": \"drlee\", \"password\": \"$DEMO_PASSWORD\", \"display_name\": \"Dr. Sarah Lee\", \"user_type\": \"person\"}")
    DRLEE_TOKEN=$(echo "$DRLEE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_token',''))")
    DRLEE_DID=$(echo "$DRLEE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('did',''))")

    if [ -z "$DRLEE_TOKEN" ]; then
        fail "Failed to initialize Dr. Lee's pod: $DRLEE_RESP"
    fi
    ok "Dr. Lee initialized: DID=$DRLEE_DID"

    # Store health data in Molly's pod via Memory API
    log "Storing health data in Molly's vault..."
    curl -s -X POST "http://localhost:$MOLLY_PORT/api/memory/store" \
        -H "Content-Type: application/json" \
        -H "Cookie: trustmesh_session=$MOLLY_TOKEN" \
        -d '{"content": "Blood pressure 140/90 mmHg, slightly elevated. Heart rate 78 bpm. Weight 145 lbs.", "title": "Health Check - Morning", "category": "health", "visibility": "private"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Stored: {d[\"id\"][:8]}...')"

    curl -s -X POST "http://localhost:$MOLLY_PORT/api/memory/store" \
        -H "Content-Type: application/json" \
        -H "Cookie: trustmesh_session=$MOLLY_TOKEN" \
        -d '{"content": "Started taking Lisinopril 10mg daily for blood pressure. Follow up in 2 weeks.", "title": "Medication Update", "category": "health", "visibility": "private"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Stored: {d[\"id\"][:8]}...')"

    ok "Health data stored in Molly's encrypted vault"

    # Verify recall works
    log "Testing memory recall on Molly's pod..."
    RECALL=$(curl -s -X POST "http://localhost:$MOLLY_PORT/api/memory/recall" \
        -H "Content-Type: application/json" \
        -H "Cookie: trustmesh_session=$MOLLY_TOKEN" \
        -d '{"query": "blood pressure", "top_k": 5}')
    RESULT_COUNT=$(echo "$RECALL" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('results',[])))")
    if [ "$RESULT_COUNT" -gt 0 ]; then
        ok "Memory recall found $RESULT_COUNT results for 'blood pressure'"
    else
        warn "Memory recall returned 0 results (FTS may need indexing)"
    fi

    # Show memory health
    log "Checking memory API health..."
    for port in $MOLLY_PORT $DRLEE_PORT; do
        HEALTH=$(curl -s "http://localhost:$port/api/memory/health")
        STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))")
        ok "Pod :$port memory health: $STATUS"
    done

    echo ""
    ok "Demo setup complete!"
    echo ""
    echo "  Molly (patient) on :$MOLLY_PORT — 2 health capsules in vault"
    echo "  Dr. Lee (doctor) on :$DRLEE_PORT — empty vault"
    echo ""
    echo "  Molly session: $MOLLY_TOKEN"
    echo "  Dr. Lee session: $DRLEE_TOKEN"
    echo ""
    echo "Next steps:"
    echo "  1. Connect pods and establish trust for cross-pod queries"
    echo "  2. Use ZeroClaw with --memory trustmesh to query through agent"
    echo "  3. Test trust boundaries: public queries see nothing, private sees all"
}

# ── Teardown ───────────────────────────────────────────────────────

teardown() {
    log "Stopping demo pods..."
    for pidfile in "$CORE_DIR/data/molly.pid" "$CORE_DIR/data/drlee.pid"; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
                ok "Stopped PID $pid"
            fi
            rm -f "$pidfile"
        fi
    done
    rm -f "$MOLLY_DB" "$DRLEE_DB"
    ok "Cleanup complete"
}

# ── Main ───────────────────────────────────────────────────────────

case "${1:-demo}" in
    setup)    setup ;;
    teardown) teardown ;;
    demo)
        setup
        echo ""
        log "Demo complete. Run '$0 teardown' when done."
        ;;
    *)
        echo "Usage: $0 [setup|teardown|demo]"
        exit 1
        ;;
esac
