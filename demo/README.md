# TrustMesh Hackathon Demo

Trust-aware knowledge sharing for personal AI agents. Three scenarios showing how agents gossip across trust boundaries to help the Johnson family.

## Prerequisites

```bash
# 1. Start the backend + frontend
./dev.sh start

# 2. Verify server is running
curl http://localhost:8000/health
# → {"status":"ok","service":"trustmesh-core"}

# 3. Open the UI
open http://localhost:3050
```

**Required env vars** (in `.env` or exported):
- `ANTHROPIC_API_KEY` — for LLM calls (required)
- `VOYAGE_API_KEY` — for embeddings (optional, falls back to local)

## Quick Start — Run Everything

```bash
# One command: setup + all 3 demos in sequence
bash demo/demo-all.sh
```

Each demo pauses between steps (press Enter to continue). Takes ~3 minutes total.

## Individual Demos

### Setup (required first)

```bash
source demo/demo-setup.sh
```

Logs in all 8 demo users, saves sessions to `/tmp/trustmesh-demo/`. Must run before any individual demo.

### Demo 1: Grandma's Visit (Peter, CLI)

```bash
bash demo/demo-1-grandma-visit.sh
```

**Story:** Peter needs to prepare for Grandma Rose's week-long visit. He doesn't know the medical details — Molly manages Rose's care.

**What happens:**
1. Peter asks his agent about the visit
2. Agent searches Peter's vault → finds visit dates
3. Agent gossips with Molly's agent (via shared "Johnsons" network)
4. Molly's agent returns the full care routine (medications, dialysis, diet)
5. Peter gets one combined actionable answer

**Trust enforced:** Peter sees internal family data but NOT Molly's private journal (her stress about Rose's declining health).

**Expected output:** ~1600 chars, 1 peer query, ~28s latency.

### Demo 2: Birthday Allergies (Molly, multi-network)

```bash
bash demo/demo-2-birthday-allergies.sh
```

**Story:** Bill turns 14. Molly is planning a neighborhood party for 9 guests across 6 trust networks. Grandma Rose is doing the grocery run.

**Part 1 — Molly asks about allergies:**
- Agent queries 4-5 peers across family + friend + neighbor networks
- Finds: Bill's PEANUT ALLERGY (critical), Bill's lactose intolerance, Rose's lactose intolerance + low sodium

**Part 2 — Save allergy summary:**
- Agent saves a "Bill Birthday Party - Food Restrictions" capsule (internal visibility)

**Part 3 — Rose checks the list:**
- Rose cross-queries Molly's agent from the grocery store
- Trust resolved via "Rose's Care Circle" network
- Gets the food restriction summary

**Trust enforced:** Rose sees internal capsules but NOT Molly's salary, career plans, or private journal.

**Expected output:** Part 1: ~1600 chars, 4+ peer queries, ~35s. Part 3: ~400 chars, network trust, ~4s.

### Demo 3: Emergency (UCAN tokens)

```bash
bash demo/demo-3-emergency.sh
```

**Story:** Rose is in a car accident. She's unconscious. The hospital needs her medical records NOW.

**Step 1 — Hospital issues UCAN token:**
- Riverside General issues a cryptographic token scoped to health data
- Role: attending_physician, expires in 30 minutes

**Step 2 — Access emergency health data:**
- Token presented (no password needed)
- 8 health capsules returned: allergies, medications, conditions, surgical history, BP/dialysis, emergency contacts, DNR

**Step 3 — Family notifications:**
- Molly gets "Emergency: Grandma Rose's medical data accessed"
- Peter gets the same alert
- Dorothy (bridge partner, Care Circle member) gets alerted

**Step 4 — Audit trail:**
- Rose's account shows exactly who accessed what, when, and why

**Trust enforced:** Only health-category capsules shared. Rose's garden tips, daily routine, private journal, financial info — all hidden.

**Expected output:** Token issued, 8 capsules, 3 family notified.

## MCP Demo (Peter on Claude Code)

Peter is logged into the TrustMesh MCP server. He can ask questions directly through Claude Code.

### Setup

```bash
# Login as Peter (if not already)
cd trustmesh-core
uv run trustmesh login --pod http://localhost:8000 --user peter
# Password: TrustMesh-demo-2026
```

The MCP server is configured in `.mcp.json` and auto-connects when Claude Code starts.

### Demo Prompts

Type these directly in Claude Code:

**1. Search vault:**
> "Use TrustMesh to search my vault for information about Grandma Rose's upcoming visit."

**2. Ask agent (with gossip):**
> "Ask my TrustMesh agent: Grandma Rose is coming next week - what do I need to prepare for her stay?"

**3. Check connections:**
> "Show me my TrustMesh connections and trust networks"

**4. Pod status:**
> "Check my TrustMesh pod status"

**5. Save knowledge:**
> "Save to my TrustMesh vault: I confirmed the guest room is ready for Grandma Rose. Set up the dialysis machine on Feb 19."

### What Claude Code Does

- `search_vault` → semantic search of Peter's encrypted vault
- `ask_agent` → triggers gossip to Molly's agent for care details
- `list_connections` → shows Peter's trusted connections
- `pod_status` → pod health, providers, peers

## UI Demo (Molly)

1. Open http://localhost:3050
2. Click "Molly Johnson" to login
3. Show the dashboard: connections, networks, vault capsules
4. Check the notification bell — emergency alerts from Demo 3
5. Go to "Ask Agents" — see query history
6. Switch to Grandma Rose — see emergency access audit trail

## The Johnson Family

| Person | Role | Vault | Notes |
|--------|------|-------|-------|
| Peter | Dad, electrician | 14 capsules (3 private) | CLI/MCP user |
| Molly | Mom, PM at TechCorp | 12 capsules (3 private) | UI user |
| Bill | Son, 14 | 6 capsules (2 private) | Peanut allergy! |
| Jane | Daughter, 16 | 6 capsules (2 private) | Soccer player |
| Grandma Rose | 78, CKD stage 3b | 15 capsules (5 private) | Complex medical needs |

## Trust Networks

| Network | Members | Purpose |
|---------|---------|---------|
| The Johnsons | Peter, Molly, Jane, Bill | Family data sharing |
| Rose's Care Circle | Molly, Peter, Rose, Dorothy | Medical care coordination |
| Lincoln High Soccer | Jane, Amy, Coach Davis | Team schedules |
| Roosevelt Coding Club | Bill, Marcus, Ms. Rivera | Coding projects |
| Riverside Neighbors | Peter, Molly, Linda, Tom | Neighborhood info |
| Riverside Bridge Club | Rose, Dorothy | Social activities |

## Sensitivity & Privacy

### What counts as "sensitive"?

The model router classifies data as **sensitive** if:

**By capsule category:**
- `health` / `medical` — medications, allergies, diagnoses, blood pressure
- `financial` — bank accounts, salary, investments, credit cards
- `legal` — end-of-life wishes, contracts, trusts
- `insurance` — policy numbers, claims

**By question keywords:**
- Medical: "diagnosis", "prescription", "medication", "dialysis", "surgery"
- Financial: "bank", "ssn", "credit card", "salary", "tax", "income"
- Insurance: "policy number", "claim"

### How routing works

```
Query arrives
  → detect_sensitivity(capsules, question)
  → if "sensitive" → route to TEE (Redpill, TDX/GPU enclave)
  → if "standard" → Anthropic
```

**Current state:** TEE is active via Redpill (`REDPILL_API_KEY`). Sensitive queries route to TEE models running inside hardware enclaves — the model provider literally cannot see your plaintext.

| Sensitivity | Provider | Model |
|-------------|----------|-------|
| standard | Anthropic | Claude Haiku 4.5 (fast) / Opus 4.6 (default) |
| sensitive | Redpill TEE | GLM-4.7-flash (fast) / GLM-5 (default) / Kimi-K2-thinking (reasoning) |

**Proof from server logs:**
```
[ROUTING] sensitivity=standard  → Anthropic (claude-haiku-4-5-20251001)
[ROUTING] sensitivity=sensitive → TEE (redpill, model=z-ai/glm-4.7-flash)
```

**What stays private (never sent to any LLM during cross-queries):**
- `private` visibility capsules are only accessible on self-query
- Cross-queries only see `internal` (if trusted network) or `open` capsules
- Emergency UCAN only sees `health` category + `emergency_accessible=true`

### Example: What Peter's cross-query CANNOT see

When Peter's agent gossips with Molly's agent:
- **Sees:** Rose's care routine, medical contacts, family schedules (internal, shared network)
- **Hidden:** Molly's salary ($128k), Stripe recruiter talks, worries about Rose's kidneys (private)
- **Hidden:** Bill's D+ in English, Jane's diary about Tyler (private, different owners)

## Capsule Visibility Matrix

| Visibility | Self-query | Network trust | Public trust | Emergency |
|------------|-----------|---------------|-------------|-----------|
| private | Yes | No | No | No |
| internal | Yes | Yes (shared networks) | No | No |
| open | Yes | Yes | Yes | No |
| internal+emergency | Yes | Yes | No | Yes (health only) |

## Troubleshooting

**Server won't start:**
```bash
./dev.sh stop && ./dev.sh start
```

**"Vault key not available":** Re-seed and restart:
```bash
cd trustmesh-core
rm -f trustmesh.db*
uv run python -m src.seed
./dev.sh start
```

**Demo setup fails ("FAIL: peter"):** The server needs to be running first. Check `curl http://localhost:8000/health`.

**MCP not connecting:** Check `.mcp.json` exists in project root. Restart Claude Code after login.

**Slow responses (~30-40s):** Normal — the agent does semantic search + LLM reasoning + peer gossip. Emergency access (no LLM) is instant.

## File Reference

| File | Purpose |
|------|---------|
| `demo/demo-setup.sh` | Login all users, save sessions |
| `demo/demo-1-grandma-visit.sh` | Peter asks about Rose's visit |
| `demo/demo-2-birthday-allergies.sh` | Molly checks allergies, shares with Rose |
| `demo/demo-3-emergency.sh` | UCAN token, health access, family alerts |
| `demo/demo-all.sh` | Run setup + all 3 demos |
| `demo/demo-mcp-peter.md` | MCP prompts for Claude Code |
