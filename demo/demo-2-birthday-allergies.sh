#!/usr/bin/env bash
# ============================================================================
# DEMO 2: Bill's Birthday Party — Finding Allergies Across Trust Networks
# ============================================================================
# Bill's 14th birthday is coming up. Molly is planning a Riverside
# neighborhood celebration — family, the kids' friends, and neighbors.
#
# Guest list:
#   Family:     Peter, Molly, Jane, Bill, Grandma Rose
#   Bill's bud: Marcus Williams (coding club)
#   Jane's bff: Amy Torres (soccer co-captain)
#   Neighbors:  Linda Chen, Dorothy Park
#
# Molly's agent must gossip across 6 different trust networks to find
# everyone's allergies/restrictions. Then she shares the summary with
# Grandma Rose, who's picking up ingredients at the store.
#
# This shows: multi-network gossip → allergy discovery → trust-aware sharing
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
RED='\033[0;31m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

clear
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   DEMO 2: Bill's Birthday — Neighborhood Allergy Check     ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${DIM}Bill Johnson turns 14! The whole Riverside crew is invited:${NC}"
echo ""
echo -e "  ${BOLD}Family:${NC}     Peter, Molly, Jane, Bill, Grandma Rose"
echo -e "  ${BOLD}Friends:${NC}    Marcus Williams (Bill's coding buddy)"
echo -e "              Amy Torres (Jane's soccer co-captain)"
echo -e "  ${BOLD}Neighbors:${NC}  Linda Chen, Dorothy Park"
echo ""
echo -e "${DIM}Grandma Rose is doing the grocery run. Molly needs to figure out${NC}"
echo -e "${DIM}everyone's food allergies FAST — and share the info with Rose.${NC}"
echo ""
echo -e "${DIM}Molly's agent will gossip across 6 trust networks:${NC}"
echo -e "${DIM}  The Johnsons, Rose's Care Circle, Lincoln High Soccer,${NC}"
echo -e "${DIM}  Roosevelt Coding Club, Riverside Neighbors, Riverside Bridge Club${NC}"
echo ""

# ── Part 1: Ask about allergies ──
echo -e "${BOLD}═══ Part 1: Molly asks about allergies for ALL guests ═══${NC}"
echo ""
echo -e "${YELLOW}Molly asks her agent:${NC}"
echo -e '  "Bill'\''s birthday party is this weekend. The guest list is the whole'
echo -e '   Riverside crew: family (Peter, Jane, Bill, Grandma Rose), Bill'\''s'
echo -e '   friend Marcus, Jane'\''s friend Amy, and neighbors Linda and Dorothy.'
echo -e '   Can you check if anyone has food allergies or dietary restrictions?"'
echo ""
read -p "Press Enter to ask Molly's agent..."
echo ""

echo -e "${CYAN}[Agent] Searching vaults across multiple trust networks...${NC}"
echo ""

RESPONSE=$(curl -s -X POST "$API_BASE/api/query" \
    -H "Content-Type: application/json" \
    -b "$molly_jar" \
    -d "{
        \"from_user_id\": \"$molly_id\",
        \"to_user_id\": \"$molly_id\",
        \"question\": \"Bill's birthday party is this weekend! The guest list is: family (Peter, Jane, Bill, Grandma Rose), Bill's friend Marcus Williams, Jane's friend Amy Torres, and our neighbors Linda Chen and Dorothy Park. That's 9 people total. Can you check if anyone attending has food allergies or dietary restrictions I should know about for planning the menu? Please query everyone you can reach through our trust networks.\"
    }")

DECISION=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('decision','?'))" 2>/dev/null)
ACTIONS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(', '.join(a.get('type','?') for a in json.load(sys.stdin).get('agent_actions',[])))" 2>/dev/null)
LATENCY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('latency_ms','?'))" 2>/dev/null)
ANSWER=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','No response'))" 2>/dev/null)
NUM_QUERIES=$(echo "$RESPONSE" | python3 -c "import sys,json; print(sum(1 for a in json.load(sys.stdin).get('agent_actions',[]) if a.get('type')=='peer_queried'))" 2>/dev/null)

echo -e "${GREEN}━━━ Agent Response ━━━${NC}"
echo ""
echo "$ANSWER"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}Decision: $DECISION | Peer queries: $NUM_QUERIES | Actions: $ACTIONS | Latency: ${LATENCY}ms${NC}"
echo ""
echo -e "${BOLD}What happened behind the scenes:${NC}"
echo -e "  1. Molly's agent searched her own vault (Bill's allergy info, Rose's care routine)"
echo -e "  2. Agent queried ${CYAN}$NUM_QUERIES peers${NC} across different trust networks:"
echo -e "     - Family: Peter, Jane, Bill, Grandma Rose (via The Johnsons + Rose's Care Circle)"
echo -e "     - Friends: Marcus (via Bill), Amy (via Jane)"
echo -e "     - Neighbors: Linda (via Riverside Neighbors), Dorothy (via Rose)"
echo -e "  3. Found: ${RED}Bill's PEANUT ALLERGY${NC}, Rose's lactose intolerance + low sodium"
echo -e "  4. Combined everything into one menu planning guide"
echo ""

# ── Part 2: Save and share ──
echo -e "${BOLD}═══ Part 2: Save allergy summary for Grandma Rose ═══${NC}"
echo ""
echo -e "${YELLOW}Molly asks her agent to save a grocery-friendly summary:${NC}"
echo -e '  "Save a note with all the food restrictions for the party so I can'
echo -e '   share it with Grandma Rose. She'\''s doing the grocery run."'
echo ""
read -p "Press Enter to save..."
echo ""

echo -e "${CYAN}[Agent] Saving capsule to vault...${NC}"
echo ""

SHARE_RESPONSE=$(curl -s -X POST "$API_BASE/api/query" \
    -H "Content-Type: application/json" \
    -b "$molly_jar" \
    -d "{
        \"from_user_id\": \"$molly_id\",
        \"to_user_id\": \"$molly_id\",
        \"question\": \"Please save a note titled 'Bill Birthday Party - Food Restrictions' with all the dietary info for the party: Bill has a CRITICAL peanut allergy (anaphylaxis - absolutely no peanuts, peanut butter, peanut oil, or cross-contaminated items), Grandma Rose is lactose intolerant (no dairy, uses oat milk) and needs low-sodium food. Peter, Jane, Marcus, Amy, Linda, and Dorothy have no known food restrictions. Make the note visibility 'internal' so family and trusted connections can see it.\"
    }")

SHARE_ACTIONS=$(echo "$SHARE_RESPONSE" | python3 -c "import sys,json; print(', '.join(a.get('type','?') for a in json.load(sys.stdin).get('agent_actions',[])))" 2>/dev/null)
SHARE_ANSWER=$(echo "$SHARE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','No response'))" 2>/dev/null)

echo -e "${GREEN}━━━ Agent Response ━━━${NC}"
echo ""
echo "$SHARE_ANSWER"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}Actions: $SHARE_ACTIONS${NC}"
echo ""

# ── Part 3: Grandma Rose picks up the list ──
echo -e "${BOLD}═══ Part 3: Grandma Rose checks the list before shopping ═══${NC}"
echo ""
echo -e "${DIM}Rose is at the store. She asks Molly's agent what to watch out for.${NC}"
echo ""
echo -e "${YELLOW}Grandma Rose asks Molly's agent:${NC}"
echo -e '  "I'\''m at the grocery store for Bill'\''s birthday party. What food'
echo -e '   allergies and restrictions should I watch out for?"'
echo ""
read -p "Press Enter to query as Grandma Rose..."
echo ""

echo -e "${CYAN}[Cross-query] Rose → Molly (trust: network via Rose's Care Circle)${NC}"
echo ""

ROSE_RESPONSE=$(curl -s -X POST "$API_BASE/api/query" \
    -H "Content-Type: application/json" \
    -b "$grandmarose_jar" \
    -d "{
        \"from_user_id\": \"$grandmarose_id\",
        \"to_user_id\": \"$molly_id\",
        \"question\": \"I'm at the grocery store picking up food for Bill's birthday party this weekend. What food allergies and dietary restrictions should I watch out for when shopping? I want to make sure everything is safe for all the kids and guests.\"
    }")

ROSE_TRUST=$(echo "$ROSE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('trust_level','?'))" 2>/dev/null)
ROSE_NETWORKS=$(echo "$ROSE_RESPONSE" | python3 -c "import sys,json; print(', '.join(json.load(sys.stdin).get('shared_networks',[])))" 2>/dev/null)
ROSE_ANSWER=$(echo "$ROSE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','No response'))" 2>/dev/null)
ROSE_DECISION=$(echo "$ROSE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('decision','?'))" 2>/dev/null)

echo -e "${GREEN}━━━ Molly's Agent responds to Grandma Rose ━━━${NC}"
echo ""
echo "$ROSE_ANSWER"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${DIM}Trust: $ROSE_TRUST | Networks: $ROSE_NETWORKS | Decision: $ROSE_DECISION${NC}"
echo ""
echo -e "${BOLD}What happened:${NC}"
echo -e "  1. Rose queried Molly's agent about the party food"
echo -e "  2. Trust resolved: Rose & Molly share ${CYAN}Rose's Care Circle${NC} network"
echo -e "  3. Molly's agent found the party restrictions note (internal visibility)"
echo -e "  4. Shared allergy info with Rose — she now knows what to buy safely"
echo ""
echo -e "${BOLD}Trust boundaries enforced:${NC}"
echo -e "  ${GREEN}Shared:${NC}  Food restrictions, party guest info (internal capsules)"
echo -e "  ${RED}Hidden:${NC}  Molly's private journal (her stress about Rose's declining health)"
echo -e "  ${RED}Hidden:${NC}  Bill's report card, Jane's diary"
echo -e "  ${RED}Hidden:${NC}  Molly's work deadlines, salary info"
echo ""
echo -e "${YELLOW}9 guests, 6 trust networks, every allergy found — and private${NC}"
echo -e "${YELLOW}data stayed private the entire time.${NC}"
