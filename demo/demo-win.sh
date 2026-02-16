#!/usr/bin/env bash
# ============================================================================
# TrustMesh Hackathon Demo — Recording Script
# ============================================================================
#
# BEFORE recording (takes ~2 min, pre-runs the slow LLM queries):
#
#   ./demo/demo-win.sh warmup
#
# THREE windows during recording:
#
#   Terminal 1:  ./demo/demo-win.sh peter
#   Terminal 2:  ./demo/demo-win.sh molly
#   Browser:     http://localhost:3050 → login as grandmarose
#                (password: TrustMesh-demo-2026)
#
# DURING recording (just press Enter at each beat):
#
#   1. Narrate intro over Rose's browser (landing page or vault)
#   2. [Peter terminal]  → Enter → grandma visit response appears
#   3. [Molly terminal]  → Enter → allergy check response appears
#   4. [Molly terminal]  → Enter → 🚨 EMERGENCY fires (instant, live!)
#   5. [Browser]         → notification bell lights up automatically (SSE)
#                         → click it → see emergency audit entry
#   6. Narrate close
#
# ============================================================================
set -euo pipefail

API_BASE="${TRUSTMESH_DEMO_URL:-http://localhost:8000}"
DEMO_PASSWORD="TrustMesh-demo-2026"
CACHE_DIR="/tmp/trustmesh-demo"
COOKIE_DIR="$CACHE_DIR/cookies"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'
WHITE='\033[1;37m'

# ── Helpers ──

# Simulate LLM streaming — prints text line by line with a delay
stream_text() {
    local delay="${1:-0.05}"
    while IFS= read -r line; do
        echo "$line"
        sleep "$delay"
    done
}

# Animated thinking spinner — runs for N seconds
think_spinner() {
    local duration="${1:-3}"
    local msg="${2:-Thinking}"
    local end=$((SECONDS + duration))
    local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
    local i=0
    while (( SECONDS < end )); do
        printf "\r  ${CYAN}${frames[$i]} ${msg}...${NC} "
        i=$(( (i + 1) % ${#frames[@]} ))
        sleep 0.1
    done
    printf "\r  ${GREEN}✓${NC} ${msg}     \n"
}

login_user() {
    local user="$1"
    RESPONSE=$(curl -sf -X POST "$API_BASE/api/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\": \"$user\", \"password\": \"$DEMO_PASSWORD\"}" \
        -c "$COOKIE_DIR/${user}.jar" 2>&1) || { echo "FAIL"; return 1; }
    echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])"
}

# ── WARMUP ──

do_warmup() {
    echo ""
    echo -e "${BOLD}${WHITE}  TrustMesh Demo Warmup${NC}"
    echo -e "${DIM}  Pre-runs the slow agent queries so recording is instant.${NC}"
    echo ""

    # Check server
    if ! curl -sf "$API_BASE/health" > /dev/null 2>&1; then
        echo -e "  ${RED}✗${NC} Server not running at $API_BASE"
        echo ""
        echo -e "  Start it:  ${CYAN}./dev.sh start${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Server running"

    # Check API key
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        echo -e "  ${RED}✗${NC} ANTHROPIC_API_KEY not set"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} API key set"

    # Clean + reseed + restart server (server caches sessions in memory)
    echo ""
    echo -e "  ${DIM}Reseeding database (clean state)...${NC}"
    (cd trustmesh-core && rm -f trustmesh.db trustmesh.db-shm trustmesh.db-wal && uv run python -m src.seed) > /dev/null 2>&1
    echo -e "  ${GREEN}✓${NC} Fresh database"

    echo -e "  ${DIM}Restarting backend (clearing sessions)...${NC}"
    # Kill existing backend
    lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 2
    # Start fresh
    (cd trustmesh-core && nohup uv run uvicorn src.main:app --host 127.0.0.1 --port 8000 > /tmp/trustmesh-backend.log 2>&1 &)
    # Wait for it
    for i in {1..15}; do
        if curl -sf "$API_BASE/health" > /dev/null 2>&1; then break; fi
        sleep 1
    done
    if ! curl -sf "$API_BASE/health" > /dev/null 2>&1; then
        echo -e "  ${RED}✗${NC} Backend failed to restart"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Backend restarted"

    # Login
    mkdir -p "$COOKIE_DIR"
    echo ""
    echo -e "  ${DIM}Logging in demo users...${NC}"

    peter_id=$(login_user "peter")
    molly_id=$(login_user "molly")
    rose_id=$(login_user "grandmarose")
    hospital_id=$(login_user "riverside_hospital")
    login_user "emt_johnson" > /dev/null 2>&1
    login_user "dr_lee" > /dev/null 2>&1
    login_user "bill" > /dev/null 2>&1
    login_user "jane" > /dev/null 2>&1

    echo -e "  ${GREEN}✓${NC} 8 users logged in"

    # Save IDs for later
    cat > "$CACHE_DIR/ids.sh" << EOF
peter_id="$peter_id"
molly_id="$molly_id"
rose_id="$rose_id"
hospital_id="$hospital_id"
EOF

    # ── Pre-run Demo 1 ──
    echo ""
    echo -e "  ${DIM}Pre-running Demo 1: Peter asks about grandma's visit...${NC}"
    echo -e "  ${DIM}(~30s — agent searches vault + gossips with Molly)${NC}"

    DEMO1=$(curl -s -X POST "$API_BASE/api/query" \
        -H "Content-Type: application/json" \
        -b "$COOKIE_DIR/peter.jar" \
        -d "{
            \"from_user_id\": \"$peter_id\",
            \"to_user_id\": \"$peter_id\",
            \"question\": \"Grandma Rose is coming to visit next week (Feb 20-27). What do I need to prepare for her stay? Please check with Molly about the detailed care routine, medications, and any medical equipment we need set up.\"
        }")
    echo "$DEMO1" > "$CACHE_DIR/demo1.json"

    D1_OK=$(echo "$DEMO1" | python3 -c "import sys,json; r=json.loads(sys.stdin.read(), strict=False); print('ok' if r.get('response') else 'fail')" 2>/dev/null)
    if [[ "$D1_OK" != "ok" ]]; then
        echo -e "  ${RED}✗${NC} Demo 1 failed"
        echo "$DEMO1" | python3 -m json.tool 2>/dev/null || echo "$DEMO1"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Demo 1 cached"

    # ── Pre-run Demo 2 ──
    echo ""
    echo -e "  ${DIM}Pre-running Demo 2: Molly checks allergies across networks...${NC}"
    echo -e "  ${DIM}(~35s — queries multiple peers across 6 networks)${NC}"

    DEMO2=$(curl -s -X POST "$API_BASE/api/query" \
        -H "Content-Type: application/json" \
        -b "$COOKIE_DIR/molly.jar" \
        -d "{
            \"from_user_id\": \"$molly_id\",
            \"to_user_id\": \"$molly_id\",
            \"question\": \"Bill's birthday party is this weekend! Guest list: family (Peter, Jane, Bill, Grandma Rose), Bill's friend Marcus Williams, Jane's friend Amy Torres, and neighbors Linda Chen and Dorothy Park. 9 people total. Check if anyone has food allergies or dietary restrictions — query everyone you can reach through our trust networks.\"
        }")
    echo "$DEMO2" > "$CACHE_DIR/demo2.json"

    D2_OK=$(echo "$DEMO2" | python3 -c "import sys,json; r=json.loads(sys.stdin.read(), strict=False); print('ok' if r.get('response') else 'fail')" 2>/dev/null)
    if [[ "$D2_OK" != "ok" ]]; then
        echo -e "  ${RED}✗${NC} Demo 2 failed"
        echo "$DEMO2" | python3 -m json.tool 2>/dev/null || echo "$DEMO2"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Demo 2 cached"

    # ── Mark Rose's notifications as read (clean slate for emergency) ──
    curl -s -X PUT "$API_BASE/api/users/$rose_id/notifications/read-all" \
        -b "$COOKIE_DIR/grandmarose.jar" > /dev/null 2>&1
    curl -s -X PUT "$API_BASE/api/users/$molly_id/notifications/read-all" \
        -b "$COOKIE_DIR/molly.jar" > /dev/null 2>&1
    curl -s -X PUT "$API_BASE/api/users/$peter_id/notifications/read-all" \
        -b "$COOKIE_DIR/peter.jar" > /dev/null 2>&1

    # Done
    echo ""
    echo -e "${GREEN}${BOLD}  ✓ Warmup complete!${NC}"
    echo ""
    echo -e "  Now open ${BOLD}three windows${NC}:"
    echo ""
    echo -e "    ${CYAN}Terminal 1:${NC}  ./demo/demo-win.sh peter"
    echo -e "    ${CYAN}Terminal 2:${NC}  ./demo/demo-win.sh molly"
    echo -e "    ${CYAN}Browser:${NC}    http://localhost:3050"
    echo -e "                 Login as ${BOLD}grandmarose${NC} / ${BOLD}TrustMesh-demo-2026${NC}"
    echo ""
    echo -e "  ${DIM}Press Enter at each beat during recording. That's it.${NC}"
    echo ""
}

# ── PETER'S TERMINAL ──

do_peter() {
    if [[ ! -f "$CACHE_DIR/demo1.json" ]]; then
        echo "Run './demo/demo-win.sh warmup' first"
        exit 1
    fi

    ANSWER=$(python3 -c "import json; print(json.loads(open('$CACHE_DIR/demo1.json').read(), strict=False).get('response',''))")
    PEERS=$(python3 -c "import json; print(sum(1 for a in json.loads(open('$CACHE_DIR/demo1.json').read(), strict=False).get('agent_actions',[]) if a.get('type')=='peer_queried'))")

    clear
    echo ""
    echo -e "${BOLD}${WHITE}  Peter Johnson${NC}  ${DIM}— electrician, dad of two${NC}"
    echo ""
    echo -e "  ${DIM}In TrustMesh, every person has an encrypted vault and a personal${NC}"
    echo -e "  ${DIM}AI agent. Peter's vault has his work notes, guitar tabs, house${NC}"
    echo -e "  ${DIM}projects — 14 capsules total, 3 marked private (only he can see).${NC}"
    echo ""
    echo -e "  ${DIM}His wife Molly manages Grandma Rose's medical care. That info lives${NC}"
    echo -e "  ${DIM}in Molly's vault — Peter doesn't have direct access to it.${NC}"
    echo -e "  ${DIM}But their agents can gossip through shared trust networks.${NC}"
    echo ""
    echo ""
    echo -e "  ${YELLOW}\$${NC} trustmesh agent ask \\"
    echo -e "      ${WHITE}\"Grandma Rose is coming next week. What do I need to${NC}"
    echo -e "      ${WHITE} prepare? Check with Molly about the care routine.\"${NC}"
    echo ""
    echo ""
    read -rsp "$(echo -e "  ${DIM}[Enter]${NC}")"
    echo ""
    echo ""
    think_spinner 3 "Searching Peter's vault"
    think_spinner 4 "Gossiping with Molly's agent"
    echo ""
    echo -e "${GREEN}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "$ANSWER" | fold -s -w 72 | sed 's/^/  /' | stream_text 0.04
    echo ""
    echo -e "${GREEN}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${GREEN}✓${NC} Peter's vault: visit dates, house prep notes"
    echo -e "  ${GREEN}✓${NC} Molly's agent: care routine, medications, dialysis"
    echo -e "  ${DIM}  (shared via ${CYAN}The Johnsons${NC}${DIM} + ${CYAN}Rose's Care Circle${NC}${DIM} networks)${NC}"
    echo -e "  ${RED}✗${NC} Molly's private journal (stress about Rose's health) ${DIM}— blocked${NC}"
    echo -e "  ${RED}✗${NC} Molly's salary, recruiter talks ${DIM}— blocked${NC}"
    echo ""
}

# ── MOLLY'S TERMINAL ──

do_molly() {
    if [[ ! -f "$CACHE_DIR/demo2.json" || ! -f "$CACHE_DIR/ids.sh" ]]; then
        echo "Run './demo/demo-win.sh warmup' first"
        exit 1
    fi
    source "$CACHE_DIR/ids.sh"

    ANSWER=$(python3 -c "import json; print(json.loads(open('$CACHE_DIR/demo2.json').read(), strict=False).get('response',''))")
    PEERS=$(python3 -c "import json; print(sum(1 for a in json.loads(open('$CACHE_DIR/demo2.json').read(), strict=False).get('agent_actions',[]) if a.get('type')=='peer_queried'))")

    clear
    echo ""
    echo -e "${BOLD}${WHITE}  Molly Johnson${NC}  ${DIM}— project manager, mom of two${NC}"
    echo ""
    echo -e "  ${DIM}Molly's vault has 12 capsules — work deadlines, family schedules,${NC}"
    echo -e "  ${DIM}Rose's care routine. 3 are private: her salary, her journal about${NC}"
    echo -e "  ${DIM}Rose's declining health, her recruiter conversations. No one sees those.${NC}"
    echo ""
    echo -e "  ${DIM}Bill turns 14 this weekend. 9 guests across 6 trust networks:${NC}"
    echo -e "  ${DIM}family, Bill's coding club, Jane's soccer team, neighbors.${NC}"
    echo ""
    echo ""
    echo -e "  ${YELLOW}\$${NC} trustmesh agent ask \\"
    echo -e "      ${WHITE}\"Bill's birthday — 9 guests across family, friends,${NC}"
    echo -e "      ${WHITE} and neighbors. Any food allergies or restrictions?\"${NC}"
    echo ""
    echo ""
    read -rsp "$(echo -e "  ${DIM}[Enter]${NC}")"
    echo ""
    echo ""
    think_spinner 2 "Searching Molly's vault"
    think_spinner 3 "Querying Peter's agent"
    think_spinner 3 "Querying across friend + neighbor networks"
    echo ""
    echo -e "${GREEN}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "$ANSWER" | fold -s -w 72 | sed 's/^/  /' | stream_text 0.04
    echo ""
    echo -e "${GREEN}  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${GREEN}✓${NC} Queried ${CYAN}${PEERS} peers${NC} across 6 trust networks"
    echo -e "  ${GREEN}✓${NC} Found: ${RED}${BOLD}Bill's PEANUT ALLERGY${NC} (critical)"
    echo -e "  ${GREEN}✓${NC} Found: Rose's lactose intolerance + low sodium"
    echo -e "  ${RED}✗${NC} Jane's diary, Bill's report card ${DIM}— blocked (private)${NC}"
    echo -e "  ${RED}✗${NC} Molly's salary, Peter's client list ${DIM}— blocked (private)${NC}"
    echo ""
    echo ""

    # ── Emergency beat ──
    echo -e "  ${DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${RED}${BOLD}  EMERGENCY${NC}"
    echo ""
    echo -e "  ${DIM}Rose was driving home from the grocery store.${NC}"
    echo -e "  ${DIM}Car accident. She's unconscious. Hospital needs her records.${NC}"
    echo ""
    echo ""
    read -rsp "$(echo -e "  ${DIM}[Enter to trigger emergency]${NC}")"
    echo ""
    echo ""

    # Issue UCAN token
    think_spinner 2 "Hospital issuing UCAN token"

    TOKEN_RESPONSE=$(curl -s -X POST "$API_BASE/api/emergency/token" \
        -H "Content-Type: application/json" \
        -b "$COOKIE_DIR/riverside_hospital.jar" \
        -d "{
            \"issuer_user_id\": \"$hospital_id\",
            \"patient_username\": \"grandmarose\",
            \"role\": \"attending_physician\",
            \"practitioner_name\": \"Dr. Sarah Lee\",
            \"npi\": \"1234567890\",
            \"case_id\": \"ER-20260216-001\",
            \"reason\": \"Motor vehicle accident - unconscious patient\",
            \"duration_seconds\": 1800
        }")

    TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token','FAILED'))" 2>/dev/null)

    if [[ "$TOKEN" == "FAILED" ]]; then
        echo -e "  ${RED}Token failed!${NC}"
        echo "$TOKEN_RESPONSE"
        return
    fi

    echo -e "  ${GREEN}✓${NC} Token: ${BOLD}attending_physician${NC} — health data only, 30 min"
    echo ""

    # Access health data
    think_spinner 2 "Accessing Rose's health records"

    ACCESS=$(curl -s -X POST "$API_BASE/api/emergency/access" \
        -H "Content-Type: application/json" \
        -d "{\"token\": \"$TOKEN\", \"patient_username\": \"grandmarose\"}")

    COUNT=$(echo "$ACCESS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('capsule_count','?'))" 2>/dev/null)
    NOTIFIED=$(echo "$ACCESS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('family_notified','?'))" 2>/dev/null)

    echo ""
    echo -e "  ${GREEN}${BOLD}$COUNT health records${NC} returned:"
    echo ""

    echo "$ACCESS" | python3 -c "
import sys, json
for c in json.load(sys.stdin).get('capsules', []):
    print(f'    \033[0;32m•\033[0m {c.get(\"title\", \"?\")}')
" 2>/dev/null

    echo ""
    echo -e "  ${GREEN}✓${NC} ${BOLD}${NOTIFIED} family members${NC} notified (Molly, Peter, Dorothy)"
    echo -e "  ${RED}✗${NC} Garden tips, finances, daily routine ${DIM}— untouched${NC}"
    echo ""
    echo -e "  ${DIM}Token expires in 30 min. Full audit trail on Rose's account.${NC}"
    echo ""
    echo -e "  ${YELLOW}→ Check Rose's browser — notification bell just lit up.${NC}"
    echo ""
}

# ── Help ──

show_help() {
    echo ""
    echo -e "${BOLD}TrustMesh Demo — Recording Script${NC}"
    echo ""
    echo "  Before recording:"
    echo "    ./demo/demo-win.sh warmup     # Reseed + pre-run queries (~2 min)"
    echo ""
    echo "  Three windows during recording:"
    echo "    ./demo/demo-win.sh peter      # Terminal 1: Peter's grandma visit"
    echo "    ./demo/demo-win.sh molly      # Terminal 2: Allergies + Emergency"
    echo "    http://localhost:3050          # Browser: login as grandmarose"
    echo ""
    echo "  Press Enter at each beat. That's it."
    echo ""
}

# ── Main ──

case "${1:-help}" in
    warmup)    do_warmup ;;
    peter)     do_peter ;;
    molly)     do_molly ;;
    *)         show_help ;;
esac
