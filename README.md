# TrustMesh

Trust-aware knowledge sharing for AI agents.

Personal AI agents hold rich knowledge capsules (memories, skills, procedures, schedules) in encrypted vaults, organized into user-created networks with manual connection approval. Every query crosses a trust boundary evaluated by Opus 4.6 and guarded by Citadel.

## Architecture

```
trustmesh-ui (Next.js 16)  →  trustmesh-core (Python/FastAPI)  →  Citadel (Go)
```

## Quick Start

### Backend
```bash
cd trustmesh-core
uv sync
uv run python -m src.seed    # seed demo data
uv run uvicorn src.main:app --reload --port 8000
```

### Frontend
```bash
cd trustmesh-ui
bun install
bun dev
```

### Citadel (optional, for security scanning)
```bash
cd citadel-ref
go build -o citadel ./cmd/gateway
./citadel serve 3001
```
