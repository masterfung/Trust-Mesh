#!/usr/bin/env bash
# ============================================================================
# DEMO 1: Grandma Rose is Coming to Visit
# ============================================================================
# Peter (husband, electrician) needs to prepare for Grandma Rose's week-long
# stay. He doesn't know all the medical details — but his agent does, because
# it can gossip with Molly's agent through their trusted family network.
#
# This shows: self-query → vault search → cross-agent gossip → combined answer
# ============================================================================
set -euo pipefail

ENV_FILE="/tmp/trustmesh-demo/env.sh"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Run 'source demo/demo-setup.sh' first"
    exit 1
fi
source "$ENV_FILE"

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

clear
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║          DEMO 1: Grandma Rose is Coming to Visit           ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${DIM}Peter Johnson — licensed electrician, dad of two, guitar player.${NC}"
echo -e "${DIM}His mother-in-law Grandma Rose (78) is visiting Feb 20-27.${NC}"
echo -e "${DIM}Molly (his wife) manages Rose's medical care.${NC}"
echo ""
echo -e "${YELLOW}Peter asks his TrustMesh agent:${NC}"
echo -e "  \"Grandma Rose is coming to visit next week. What do I need to"
echo -e "   prepare? Check with Molly about the care routine.\""
echo ""
read -p "Press Enter to ask Peter's agent..."
echo ""

echo -e "${CYAN}[Agent] Searching Peter's vault + gossiping with Molly's agent...${NC}"
echo ""

# Self-query: Peter asks his agent (which will gossip with Molly)
RESPONSE=$(curl -s -X POST "$API_BASE/api/query" \
    -H "Content-Type: application/json" \
    -b "$peter_jar" \
    -d "{
        \"from_user_id\": \"$peter_id\",
        \"to_user_id\": \"$peter_id\",
        \"question\": \"Grandma Rose is coming to visit next week. What do I need to prepare for her stay? Please check with Molly about the detailed care routine and medical setup.\"
    }")

# Parse and display
DECISION=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('decision','?'))" 2>/dev/null)
TRUST=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('trust_level','?'))" 2>/dev/null)
ACTIONS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(', '.join(a.get('type','?') for a in json.load(sys.stdin).get('agent_actions',[])))" 2>/dev/null)
LATENCY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('latency_ms','?'))" 2>/dev/null)
ANSWER=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','No response'))" 2>/dev/null)

echo -e "${GREEN}━━━ Agent Response ━━━${NC}"
echo ""
echo "$ANSWER"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}Decision: $DECISION | Trust: $TRUST | Actions: $ACTIONS | Latency: ${LATENCY}ms${NC}"
echo ""
echo -e "${BOLD}What happened behind the scenes:${NC}"
echo -e "  1. Peter's agent searched his vault → found visit dates & house prep notes"
echo -e "  2. Agent realized it needed medical details → queried Molly's agent"
echo -e "  3. Trust resolved: Peter & Molly share the 'Johnsons' + 'Rose's Care Circle' networks"
echo -e "  4. Molly's agent returned care routine, medications, dialysis setup"
echo -e "  5. Peter's agent combined everything into one actionable response"
echo ""
echo -e "${YELLOW}Trust-aware gossip: Peter never accessed Molly's private journal${NC}"
echo -e "${YELLOW}(which contains her stress about grandma's declining health).${NC}"
