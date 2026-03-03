#!/usr/bin/env bash
# deploy-gcp.sh — Deploy TrustMesh 3-pod demo to Google Cloud Run
#
# Usage:
#   export GOOGLE_API_KEY=...
#   export ANTHROPIC_API_KEY=...
#   ./deploy-gcp.sh YOUR_GCP_PROJECT_ID
#
# Requirements:
#   - gcloud CLI authenticated: gcloud auth login
#   - Docker buildx installed
#   - APIs enabled: Cloud Run, Artifact Registry, Cloud Build

set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <GCP_PROJECT_ID>}"
REGION="${GCP_REGION:-us-central1}"
REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/trustmesh"

log() { echo "[deploy-gcp] $*"; }
die() { echo "[deploy-gcp] ERROR: $*" >&2; exit 1; }

# ── Validate env ──────────────────────────────────────────────────────────────

[ -n "${GOOGLE_API_KEY:-}" ]     || die "GOOGLE_API_KEY is required"
[ -n "${ANTHROPIC_API_KEY:-}" ]  || die "ANTHROPIC_API_KEY is required"

# ── Step 1: Enable required APIs ─────────────────────────────────────────────

log "Enabling required GCP APIs..."
gcloud services enable \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    --project "$PROJECT_ID" \
    --quiet

# ── Step 2: Create Artifact Registry repository ───────────────────────────────

log "Creating Artifact Registry repository..."
gcloud artifacts repositories create trustmesh \
    --repository-format=docker \
    --location="$REGION" \
    --project "$PROJECT_ID" \
    --quiet 2>/dev/null || log "Repository already exists, continuing..."

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ── Step 3: Build and push images ────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log "Building backend image..."
docker build -f "$SCRIPT_DIR/Dockerfile.backend" \
    -t "${REPO}/backend:latest" \
    "$SCRIPT_DIR"
docker push "${REPO}/backend:latest"

log "Building frontend image (placeholder API URL — overridden after deploy)..."
docker build -f "$SCRIPT_DIR/Dockerfile.frontend" \
    --build-arg NEXT_PUBLIC_API_URL="https://placeholder.run.app" \
    -t "${REPO}/frontend:latest" \
    "$SCRIPT_DIR"
docker push "${REPO}/frontend:latest"

log "Building registry image..."
docker build -f "$SCRIPT_DIR/Dockerfile.registry" \
    -t "${REPO}/registry:latest" \
    "$SCRIPT_DIR"
docker push "${REPO}/registry:latest"

# ── Step 4: Deploy registry first ────────────────────────────────────────────

log "Deploying registry service..."
REGISTRY_URL=$(gcloud run deploy trustmesh-registry \
    --image "${REPO}/registry:latest" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --platform managed \
    --allow-unauthenticated \
    --port 8100 \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 3 \
    --quiet \
    --format "value(status.url)")
log "Registry deployed: $REGISTRY_URL"

# ── Step 5: Deploy backend pods ───────────────────────────────────────────────

deploy_pod() {
    local name="$1"
    log "Deploying $name pod..."
    local url
    url=$(gcloud run deploy "trustmesh-${name}" \
        --image "${REPO}/backend:latest" \
        --region "$REGION" \
        --project "$PROJECT_ID" \
        --platform managed \
        --allow-unauthenticated \
        --port 9000 \
        --memory 1Gi \
        --cpu 1 \
        --min-instances 0 \
        --max-instances 5 \
        --set-env-vars "TRUSTMESH_POD_NAME=${name},TRUSTMESH_REGISTRY_URL=${REGISTRY_URL},GOOGLE_API_KEY=${GOOGLE_API_KEY},ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY},TAVILY_API_KEY=${TAVILY_API_KEY:-}" \
        --quiet \
        --format "value(status.url)")
    # Set the pod's own URL
    gcloud run services update "trustmesh-${name}" \
        --region "$REGION" \
        --project "$PROJECT_ID" \
        --update-env-vars "TRUSTMESH_POD_URL=${url}" \
        --quiet
    echo "$url"
}

FAMILY_URL=$(deploy_pod "family")
HOSPITAL_URL=$(deploy_pod "hospital")
WORK_URL=$(deploy_pod "work")

log "Pods deployed:"
log "  family:   $FAMILY_URL"
log "  hospital: $HOSPITAL_URL"
log "  work:     $WORK_URL"

# ── Step 6: Wire pods via federation API ──────────────────────────────────────

log "Wiring federation between pods..."

wire_pods() {
    local from_url="$1" to_url="$2" to_name="$3"
    # Get auth cookie from family pod
    local cookie
    cookie=$(curl -s -c /tmp/tm_cookies_${to_name}.txt \
        -X POST "${from_url}/api/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"username":"molly","password":"TrustMesh-demo-2026"}' \
        -w "%{http_code}" -o /dev/null)
    if [ "$cookie" = "200" ]; then
        curl -s -X POST "${from_url}/api/pod/peers" \
            -H "Content-Type: application/json" \
            -b /tmp/tm_cookies_${to_name}.txt \
            -d "{\"url\":\"${to_url}\",\"name\":\"${to_name}\"}" > /dev/null
        log "  ✓ ${from_url} → ${to_name} wired"
    else
        log "  ! Could not authenticate with ${from_url} (HTTP ${cookie})"
    fi
}

# Wire all pairs
wire_pods "$FAMILY_URL" "$HOSPITAL_URL" "hospital"
wire_pods "$FAMILY_URL" "$WORK_URL" "work"
wire_pods "$HOSPITAL_URL" "$FAMILY_URL" "family"
wire_pods "$HOSPITAL_URL" "$WORK_URL" "work"
wire_pods "$WORK_URL" "$FAMILY_URL" "family"
wire_pods "$WORK_URL" "$HOSPITAL_URL" "hospital"

# ── Step 7: Deploy frontend pointing at family pod ───────────────────────────

log "Rebuilding frontend with real API URL ($FAMILY_URL)..."
docker build -f "$SCRIPT_DIR/Dockerfile.frontend" \
    --build-arg NEXT_PUBLIC_API_URL="$FAMILY_URL" \
    -t "${REPO}/frontend:latest" \
    "$SCRIPT_DIR"
docker push "${REPO}/frontend:latest"

log "Deploying frontend..."
FRONTEND_URL=$(gcloud run deploy trustmesh-frontend \
    --image "${REPO}/frontend:latest" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --platform managed \
    --allow-unauthenticated \
    --port 8080 \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 5 \
    --set-env-vars "NEXT_PUBLIC_API_URL=${FAMILY_URL}" \
    --quiet \
    --format "value(status.url)")

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════"
echo "  TrustMesh 3-Pod Demo — Deployed!"
echo "════════════════════════════════════════════"
echo ""
echo "  Frontend (start here):"
echo "    $FRONTEND_URL"
echo ""
echo "  Pods:"
echo "    Family:   $FAMILY_URL"
echo "    Hospital: $HOSPITAL_URL"
echo "    Work:     $WORK_URL"
echo "    Registry: $REGISTRY_URL"
echo ""
echo "  Demo credentials:"
echo "    molly / TrustMesh-demo-2026"
echo "    grandmarose / TrustMesh-demo-2026"
echo ""
echo "  Live Agent demo flow:"
echo "    1. Login as molly → Open Live Agent"
echo "    2. Ask: 'What does Dr. Lee know about Rose?'"
echo "    3. Wait ~5 min → agent proactively reports scheduling conflict"
echo "    4. Switch to grandmarose → say 'I've been in an accident'"
echo "       → trigger_emergency fires → UCAN token issued → family notified"
echo ""
