#!/usr/bin/env bash
# ============================================================================
# DEMO 3: Emergency — Grandma Rose's Car Accident
# ============================================================================
# Grandma Rose is in a car accident on the way back from the store.
# EMT arrives → Hospital issues UCAN token → accesses her health data →
# family (Molly & Peter) get emergency alerts.
#
# This shows: UCAN token auth → emergency data access → family notifications
#             → audit trail on grandma's account
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
MAGENTA='\033[0;35m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

clear
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   ${RED}DEMO 3: Emergency — Grandma Rose's Car Accident${NC}${BOLD}          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${DIM}Grandma Rose (78) is driving back from the grocery store.${NC}"
echo -e "${DIM}She's in a car accident. EMT arrives, she's unconscious.${NC}"
echo -e "${DIM}The hospital needs her medical data — allergies, medications, DNR status.${NC}"
echo ""
echo -e "${RED}Grandma Rose has: CKD stage 3b, type 2 diabetes, hypertension,${NC}"
echo -e "${RED}penicillin allergy, DNR on file, and is on 6 medications.${NC}"
echo ""

# ── Step 1: Hospital issues UCAN token ──
echo -e "${BOLD}═══ Step 1: Riverside General Hospital issues emergency UCAN token ═══${NC}"
echo ""
echo -e "${DIM}The ER physician (Dr. Sarah Lee) needs Rose's medical records NOW.${NC}"
echo -e "${DIM}The hospital's TrustMesh agent issues a UCAN token scoped to health data.${NC}"
echo ""
read -p "Press Enter to issue UCAN token..."
echo ""

echo -e "${CYAN}[UCAN] Issuing emergency token...${NC}"

TOKEN_RESPONSE=$(curl -s -X POST "$API_BASE/api/emergency/token" \
    -H "Content-Type: application/json" \
    -b "$riverside_hospital_jar" \
    -d "{
        \"issuer_user_id\": \"$riverside_hospital_id\",
        \"patient_username\": \"grandmarose\",
        \"role\": \"attending_physician\",
        \"practitioner_name\": \"Dr. Sarah Lee\",
        \"npi\": \"1234567890\",
        \"case_id\": \"ER-20260215-001\",
        \"reason\": \"Motor vehicle accident - unconscious patient brought by ambulance\",
        \"duration_seconds\": 1800
    }")

TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token','FAILED'))" 2>/dev/null)
ROLE=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('role','?'))" 2>/dev/null)
EXPIRES=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('expires_in','?'))" 2>/dev/null)
SCOPE=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; r=json.load(sys.stdin).get('scope',{}); print(f'categories={r.get(\"categories\")}, keywords={len(r.get(\"keywords\",[]))} terms')" 2>/dev/null)

if [[ "$TOKEN" == "FAILED" ]]; then
    echo -e "${RED}Token issuance failed!${NC}"
    echo "$TOKEN_RESPONSE"
    exit 1
fi

echo -e "${GREEN}UCAN Token Issued${NC}"
echo -e "  Role:      $ROLE"
echo -e "  Expires:   ${EXPIRES}s (30 minutes)"
echo -e "  Scope:     $SCOPE"
echo -e "  Token:     ${TOKEN:0:50}..."
echo -e "  Case ID:   ER-20260215-001"
echo -e "  Reason:    Motor vehicle accident - unconscious patient"
echo ""
echo -e "${DIM}The token is cryptographically signed by the hospital's ed25519 key.${NC}"
echo -e "${DIM}It can ONLY access health-category capsules within the scope.${NC}"
echo ""

# ── Step 2: Access emergency health data ──
echo -e "${BOLD}═══ Step 2: Access Grandma Rose's emergency health data ═══${NC}"
echo ""
echo -e "${DIM}Dr. Lee presents the UCAN token to access Rose's vault.${NC}"
echo -e "${DIM}No password needed — the token IS the authorization.${NC}"
echo ""
read -p "Press Enter to access emergency data..."
echo ""

echo -e "${CYAN}[UCAN] Accessing health data with token...${NC}"
echo ""

ACCESS_RESPONSE=$(curl -s -X POST "$API_BASE/api/emergency/access" \
    -H "Content-Type: application/json" \
    -d "{
        \"token\": \"$TOKEN\",
        \"patient_username\": \"grandmarose\"
    }")

PATIENT=$(echo "$ACCESS_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('patient_name','?'))" 2>/dev/null)
COUNT=$(echo "$ACCESS_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('capsule_count','?'))" 2>/dev/null)
FAMILY=$(echo "$ACCESS_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('family_notified','?'))" 2>/dev/null)

echo -e "${GREEN}Emergency Data Accessed — $COUNT capsules for $PATIENT${NC}"
echo -e "${MAGENTA}Family notified: $FAMILY members (Molly, Peter, Dorothy)${NC}"
echo ""

# Display each capsule
echo "$ACCESS_RESPONSE" | python3 -c "
import sys, json
r = json.load(sys.stdin)
for i, c in enumerate(r.get('capsules', []), 1):
    title = c.get('title', '?')
    content = c.get('content', '')[:200]
    print(f'  {i}. {title}')
    print(f'     {content}')
    print()
" 2>/dev/null

echo ""

# ── Step 3: Check family notifications ──
echo -e "${BOLD}═══ Step 3: Family receives emergency alerts ═══${NC}"
echo ""
read -p "Press Enter to check notifications..."
echo ""

# Molly's notification
echo -e "${MAGENTA}[Molly's phone buzzes]${NC}"
MOLLY_NOTIF=$(curl -s "$API_BASE/api/users/$molly_id/notifications" \
    -b "$molly_jar" | python3 -c "
import sys, json
notifs = json.load(sys.stdin)
for n in notifs:
    if n['notification_type'] == 'emergency_family_alert':
        print(f'  Title: {n[\"title\"]}')
        print(f'  Body:  {n[\"body\"]}')
        break
" 2>/dev/null)
echo "$MOLLY_NOTIF"
echo ""

# Peter's notification
echo -e "${MAGENTA}[Peter's phone buzzes]${NC}"
PETER_NOTIF=$(curl -s "$API_BASE/api/users/$peter_id/notifications" \
    -b "$peter_jar" | python3 -c "
import sys, json
notifs = json.load(sys.stdin)
for n in notifs:
    if n['notification_type'] == 'emergency_family_alert':
        print(f'  Title: {n[\"title\"]}')
        print(f'  Body:  {n[\"body\"]}')
        break
" 2>/dev/null)
echo "$PETER_NOTIF"
echo ""

# ── Step 4: Grandma's audit trail ──
echo -e "${BOLD}═══ Step 4: Grandma Rose's audit trail ═══${NC}"
echo ""
echo -e "${DIM}Later, Grandma Rose (or her family) can see exactly who accessed her data:${NC}"
echo ""

ROSE_NOTIF=$(curl -s "$API_BASE/api/users/$grandmarose_id/notifications" \
    -b "$grandmarose_jar" | python3 -c "
import sys, json
notifs = json.load(sys.stdin)
for n in notifs:
    if n['notification_type'] == 'emergency_access':
        print(f'  Type:    {n[\"notification_type\"]}')
        print(f'  Title:   {n[\"title\"]}')
        print(f'  Details: {n[\"body\"]}')
        print(f'  Time:    {n[\"created_at\"]}')
        break
" 2>/dev/null)
echo "$ROSE_NOTIF"
echo ""

echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BOLD}Summary — What TrustMesh Did:${NC}"
echo ""
echo -e "  1. ${GREEN}UCAN token issued${NC} — cryptographic authorization scoped to health data"
echo -e "  2. ${GREEN}8 health capsules shared${NC} — allergies, meds, DNR, blood type, contacts"
echo -e "  3. ${GREEN}Family notified instantly${NC} — Molly, Peter, and Dorothy got alerts"
echo -e "  4. ${GREEN}Full audit trail${NC} — who accessed what, when, and why"
echo -e "  5. ${RED}Private data protected${NC} — Rose's garden tips, daily routine NOT shared"
echo ""
echo -e "${YELLOW}The attending physician scope granted access to health capsules only.${NC}"
echo -e "${YELLOW}A paramedic role would see fewer capsules (no insurance, no surgical history).${NC}"
echo -e "${YELLOW}The token expires in 30 minutes — no persistent access granted.${NC}"
