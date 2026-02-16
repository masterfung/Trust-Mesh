# CLAUDE.md

Instructions for Claude Code when working on TrustMesh.

## Project Overview

TrustMesh is a trust-aware knowledge sharing platform for personal AI agents. FastAPI backend + Next.js frontend. Users have encrypted vaults, agents powered by Claude Opus 4.6, and trust networks that control information sharing.

## Repository Structure

- `trustmesh-core/` - Python backend (FastAPI, SQLAlchemy async, SQLite)
- `trustmesh-ui/` - TypeScript frontend (Next.js 15, Tailwind, D3.js)
- `trustmesh-registry/` - Public agent registry (Next.js 16, SQLite, DID verification)
- `citadel-ref/` - [Citadel](https://github.com/TryMightyAI/citadel) AI security sidecar (Go, gitignored)
- `docs/` - Architecture documentation

## Development

### Quick Start (recommended)
```bash
./dev.sh start    # Seed DB (if needed) + start backend (8000) + frontend (3050)
./dev.sh stop     # Stop both cleanly
./dev.sh restart  # Stop then start
./dev.sh status   # Show running processes
./dev.sh logs     # Tail both log files
./dev.sh seed     # Re-seed the database
```

### Manual Start
```bash
# Backend
cd trustmesh-core
uv sync                                    # Install deps
uv run python -m src.seed                  # Seed demo data
uv run uvicorn src.main:app --reload --port 8000

# Frontend
cd trustmesh-ui
bun install
bun dev --port 3050
```

### Multi-Pod Federation
```bash
# Requires: Bash 4.0+ (macOS ships 3.2 — brew install bash)
./multi-pod.sh demo       # Full setup: seed + start 16 pods + orchestrate
./multi-pod.sh status     # Show all pod health
./multi-pod.sh stop       # Stop everything
```

### Tests
```bash
cd trustmesh-core
uv run pytest tests/ -v                    # All tests
uv run pytest tests/test_ucan.py -v        # Specific file
uv run pytest tests/test_multi_pod.py -v   # Multi-pod (requires running pods)
```

### Citadel Security Sidecar
```bash
# First-time setup: download ML model + build with ONNX
./dev.sh citadel

# Or manually:
cd citadel-ref
./scripts/setup-ml.sh     # Download HuggingFace model (~685MB) + ONNX Runtime
make build-ml             # Build with ML detection
./citadel serve 3001      # Start on port 3001
```

When Citadel is running, `./dev.sh start` auto-detects it and sets `CITADEL_URL`.
Without Citadel, the Python heuristic fallback in `citadel.py` handles scanning.

For production multimodal AI security (text, images, PDFs, tool calls), see [Mighty](https://trymighty.ai/).

### Environment Variables
- `ANTHROPIC_API_KEY` - Required for LLM calls
- `VOYAGE_API_KEY` - Optional (for Voyage AI embeddings, falls back to local)
- `TAVILY_API_KEY` - Optional (for web search tool)
- `CITADEL_URL` - Optional (Citadel sidecar URL, default `http://localhost:3001`)

## Architecture Patterns

### Adding a New API Route
1. Create `trustmesh-core/src/routes/{module}.py` with `router = APIRouter(prefix="/api", tags=["{module}"])`
2. Import and register in `trustmesh-core/src/main.py`: `app.include_router(router)`
3. Add auth: `from src.auth import get_current_user_id` and `auth_user_id: str = Depends(get_current_user_id)`
4. Always verify `auth_user_id == user_id` for user-scoped endpoints
5. For mutations, verify entity ownership: `entity.owner_id == auth_user_id`

### Encryption Flow
- Vault keys stored in-memory dict (`vault_keys` in `main.py`), populated on login
- Capsule content encrypted server-side with AES-256-GCM before storage
- Decrypted server-side before API response - encrypted bytes never reach the browser
- Agent ed25519 private keys encrypted with vault key at rest

### Auth Pattern
- Session-based auth via httpOnly cookies (no tokens in JS)
- `get_current_user_id()` dependency extracts user from session cookie
- Emergency endpoints use UCAN token auth instead of session cookies
- Demo users go through normal login flow

### Database
- SQLAlchemy async with aiosqlite
- Models in `src/models.py`, schemas in `src/schemas.py`
- `src/database.py` for session management
- SQLite DB at `trustmesh-core/trustmesh.db` (gitignored)

### UCAN Tokens
- Module: `src/ucan.py`
- Format: `base64url(json_payload).base64url(ed25519_signature)`
- 4 roles: `attending_physician`, `er_nurse`, `paramedic`, `admin`
- `capsule_matches_scope()` checks category + keyword matching against role scope

### Frontend API Client
- `trustmesh-ui/src/lib/api.ts` - central `apiFetch()` wrapper
- All requests include `credentials: "include"` for cookies
- Auto-redirects to login on 401

## Test Conventions

- Tests in `trustmesh-core/tests/`
- Use `httpx.AsyncClient` with `ASGITransport` for API tests
- Test fixtures create users via `POST /api/users` and login via `POST /api/auth/login`
- Schema validation tests use Pydantic models directly (no server needed)
- UCAN tests use `generate_ed25519_keypair()` directly

## Key Files

| File | Purpose |
|------|---------|
| `src/gossip.py` | Core query engine - trust resolution -> Citadel -> semantic search -> LLM -> Citadel |
| `src/agents.py` | Opus 4.6 agent prompting, tool use (search, save, update capsules, query peers) |
| `src/crypto.py` | AES-256-GCM, Argon2id, ed25519, HKDF |
| `src/ucan.py` | UCAN token create/validate/scope-match |
| `src/trust.py` | Trust level resolution from connections and networks |
| `src/citadel.py` | Security scanning via [Citadel](https://github.com/TryMightyAI/citadel) sidecar + heuristic fallback |
| `src/seed.py` | Demo data seeder (Johnson family scenario) |
| `src/main.py` | App startup, CORS, vault_keys dict, route registration |

## Common Gotchas

- `vault_keys` dict is populated on login/seed - if a user isn't logged in, their capsules can't be decrypted
- Demo password is `DEMO_PASSWORD` constant in `src/seed.py` - only used for `is_demo=True` users
- The `from src.main import vault_keys` pattern uses lazy import to avoid circular deps
- ChromaDB runs in-process - no external service needed
- [Citadel](https://github.com/TryMightyAI/citadel) Go sidecar is optional — Python heuristic fallback handles scanning without it
- `./dev.sh citadel` does first-time ML setup (HuggingFace model download + ONNX build)
- `./dev.sh start` auto-starts Citadel if the binary exists in `citadel-ref/`
