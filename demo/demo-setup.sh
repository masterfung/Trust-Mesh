#!/usr/bin/env bash
# ============================================================================
# TrustMesh Demo Setup - Prepares all sessions for demo scripts
# Usage: source demo/demo-setup.sh
# ============================================================================
set -euo pipefail

API_BASE="${TRUSTMESH_DEMO_URL:-http://localhost:8000}"
DEMO_PASSWORD="TrustMesh-demo-2026"
COOKIE_DIR="/tmp/trustmesh-demo"
ENV_FILE="/tmp/trustmesh-demo/env.sh"

mkdir -p "$COOKIE_DIR"
rm -f "$ENV_FILE"

echo "TrustMesh Demo Setup"
echo "===================="
echo "API: $API_BASE"
echo ""

# Check server health
if ! curl -sf "$API_BASE/health" > /dev/null 2>&1; then
    echo "ERROR: Server not reachable at $API_BASE"
    echo "Start with: ./dev.sh start"
    exit 1
fi
echo "Server: OK"

# Login all demo users
USERS=(peter molly grandmarose riverside_hospital emt_johnson dr_lee bill jane)
echo ""
echo "Logging in demo users..."
for user in "${USERS[@]}"; do
    RESPONSE=$(curl -sf -X POST "$API_BASE/api/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\": \"$user\", \"password\": \"$DEMO_PASSWORD\"}" \
        -c "$COOKIE_DIR/${user}.jar" 2>&1) || { echo "  FAIL: $user"; continue; }

    ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null)
    NAME=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['display_name'])" 2>/dev/null)

    echo "export ${user}_id=\"$ID\"" >> "$ENV_FILE"
    echo "export ${user}_jar=\"$COOKIE_DIR/${user}.jar\"" >> "$ENV_FILE"
    printf "  %-22s %s (%s)\n" "$user" "$NAME" "${ID:0:8}..."
done

echo "export API_BASE=\"$API_BASE\"" >> "$ENV_FILE"
echo "export COOKIE_DIR=\"$COOKIE_DIR\"" >> "$ENV_FILE"

# Source the env file
source "$ENV_FILE"

echo ""
echo "Setup complete. Sessions saved to $ENV_FILE"
echo "Run demos with:"
echo "  bash demo/demo-1-grandma-visit.sh"
echo "  bash demo/demo-2-birthday-allergies.sh"
echo "  bash demo/demo-3-emergency.sh"
