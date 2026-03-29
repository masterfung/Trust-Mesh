#!/bin/sh
# Container entrypoint for TrustMesh pods.
# Flow: validate env → restore DB from GCS → seed if empty → start server
set -eu

log() { echo "[start] $*"; }
die() { echo "[start] FATAL: $*" >&2; exit 1; }

# ── Defaults ──────────────────────────────────────────────────────────────────
: "${PORT:=9000}"
: "${TRUSTMESH_DB:=/data/trustmesh.db}"
DB_PATH="$TRUSTMESH_DB"
GCS_BUCKET="${LITESTREAM_GCS_BUCKET:-}"
GCS_PATH="${LITESTREAM_GCS_PATH:-pods/default/db}"

# Use venv binaries directly — uv is only in the builder stage, not runtime
PYTHON="/app/.venv/bin/python"
UVICORN="/app/.venv/bin/uvicorn"

# ── Environment validation ────────────────────────────────────────────────────
# Require at least one LLM API key
[ -n "${ANTHROPIC_API_KEY:-}" ] || [ -n "${GOOGLE_API_KEY:-}" ] \
  || die "At least one LLM key required: ANTHROPIC_API_KEY or GOOGLE_API_KEY"

# POOL_SYNC_SECRET: required in production (GCS-backed), warn-only in local mode
if [ -z "${TRUSTMESH_POOL_SYNC_SECRET:-}" ]; then
  if [ -n "$GCS_BUCKET" ]; then
    die "TRUSTMESH_POOL_SYNC_SECRET is required in production (GCS replication enabled)"
  else
    log "WARNING: TRUSTMESH_POOL_SYNC_SECRET not set — federation auth disabled (local mode)"
  fi
fi

# ── Prepare data directory ─────────────────────────────────────────────────────
mkdir -p "$(dirname "$DB_PATH")"

# ── GCS restore (only when Litestream is configured) ─────────────────────────
if [ -n "$GCS_BUCKET" ]; then
  LITESTREAM_CFG="$(mktemp)"
  chmod 600 "$LITESTREAM_CFG"
  # Explicit type format — more compatible across Litestream versions
  cat > "$LITESTREAM_CFG" <<EOF
dbs:
  - path: ${DB_PATH}
    replicas:
      - type: gcs
        bucket: ${GCS_BUCKET}
        path: ${GCS_PATH}
        sync-interval: 1s
        snapshot-interval: 6h
EOF

  log "Restoring DB from gcs://${GCS_BUCKET}/${GCS_PATH} ..."
  litestream restore -config "$LITESTREAM_CFG" -if-replica-exists "$DB_PATH" || \
    log "No GCS replica yet — starting fresh DB (first cold start)"
else
  log "LITESTREAM_GCS_BUCKET not set — local mode, no GCS restore"
fi

# ── Seed if DB is empty ───────────────────────────────────────────────────────
ROW_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "0")
if [ "$ROW_COUNT" = "0" ]; then
  if [ -n "${SEED_POD_KEY:-}" ]; then
    # Cloud Run / multi-pod: seed just this pod's user
    log "Seeding pod '${SEED_POD_KEY}' ..."
    "$PYTHON" -m src.seed_multi --pod-key "${SEED_POD_KEY}"
  else
    # Local Docker / docker-compose: seed full demo dataset (all users)
    log "SEED_POD_KEY not set — seeding full demo dataset ..."
    "$PYTHON" -m src.seed
  fi
  log "Seeding complete."
else
  log "DB has ${ROW_COUNT} users — skipping seed."
fi

# Restrict DB file permissions
chmod 600 "$DB_PATH" 2>/dev/null || true

# ── Start server ──────────────────────────────────────────────────────────────
if [ -n "$GCS_BUCKET" ]; then
  log "Starting Litestream + uvicorn on :${PORT} ..."
  exec litestream replicate -config "$LITESTREAM_CFG" \
    -exec "$UVICORN src.main:app --host 0.0.0.0 --port ${PORT} --log-level info"
else
  log "Starting uvicorn on :${PORT} ..."
  exec "$UVICORN" src.main:app --host 0.0.0.0 --port "${PORT}" --log-level info
fi
