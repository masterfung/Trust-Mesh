# Credential Store: Secure Secret Management for AI Agents

> Credentials aren't knowledge. They're keys to doors. The agent needs to use the key without ever seeing it.

### Document Status

| Field | Value |
|-------|-------|
| Status | DRAFT |
| Author | TrustMesh Core Team |
| Date | February 2026 |
| Prerequisites | Phase 2 (Crypto) ✅, Phase 4 (Trust/Sessions/Rate) ✅, Phase 5 (FTS5) ✅, Transit Engine ✅ |
| Depends on | PodOS Timeline Kernel, Zig Lean Core, Transit Engine (`transit.zig` + `transit_bridge.py`) |
| Related docs | `capsule-memory-engine.md`, `lean-pod-architecture.md`, `personal-data-schema.md`, `VAULT_QUICK_REFERENCE.md` |
| Security layers | Phala TEE (infrastructure), [Citadel/Mighty](https://trymighty.ai) (AI behavior), Credential Store (secret plumbing) |

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Why Credentials Are Not Capsules](#2-why-credentials-are-not-capsules)
3. [Why TEE Doesn't Solve This](#3-why-tee-doesnt-solve-this)
4. [Research: How Others Handle This](#4-research-how-others-handle-this)
5. [Design Principles](#5-design-principles)
6. [The Brokered Credentials Pattern](#6-the-brokered-credentials-pattern)
7. [Architecture Overview](#7-architecture-overview)
8. [SQLite Schema](#8-sqlite-schema)
9. [Credential Lifecycle](#9-credential-lifecycle)
10. [Pool Credential Sharing](#10-pool-credential-sharing)
11. [Encryption Boundaries](#11-encryption-boundaries)
12. [Citadel Integration](#12-citadel-integration)
13. [Zig Kernel Modules](#13-zig-kernel-modules)
14. [Python Bridge & Agent Integration](#14-python-bridge--agent-integration)
15. [Timeline Integration](#15-timeline-integration)
16. [Agent Tools](#16-agent-tools)
17. [API Routes](#17-api-routes)
18. [Security Against Adversarial Processes](#18-security-against-adversarial-processes)
19. [Relationship to Other Systems](#19-relationship-to-other-systems)
20. [Implementation Plan](#20-implementation-plan)
21. [Risks & Mitigations](#21-risks--mitigations)

---

## 1. The Problem

TrustMesh agents today can use system credentials (ANTHROPIC_API_KEY, TAVILY_API_KEY) through `os.getenv()` in the tool execution layer. The LLM never sees these — they're injected into HTTP calls by Python code. This is correct.

But there's no way for a **user** to store **their own** credentials:
- A Stripe API key for their business
- A GitHub personal access token
- An SMTP password for email
- A Netflix login shared with family

And have their agent use those credentials in tool calls **without the secret ever touching the LLM context**.

Today, if a user told their agent "save my Stripe key sk_live_abc123", the agent would:
1. Store it as a `memory` capsule with `visibility: private`
2. Index the full content (including the key!) in FTS5 plaintext
3. Return it in future `search_vault` results — putting the raw key in the LLM context
4. Have no expiry, rotation, or usage audit

Every one of those steps is a security failure for credential material.

### What Users Need

```
"Hey agent, I set up a Stripe account. Here's my API key."
    → Agent stores it securely
    → Agent can use it in tool calls (e.g., stripe_checkout)
    → Agent NEVER reveals the key in conversation
    → Agent NEVER tells pool members the key exists
    → Key has expiry tracking and rotation reminders
    → Usage is audited (which tool, when, success/failure)

"Share my Netflix login with my sister's pod for the next month."
    → Sister's agent can use the credential
    → Sister's agent never sees the actual password
    → Share auto-expires in 30 days
    → Alice can revoke instantly
    → Every use is logged for Alice to see
```

---

## 2. Why Credentials Are Not Capsules

The CME (`capsule-memory-engine.md`) defines capsules as "living knowledge with heartbeats, decay curves, and trust boundaries." Credentials share none of these properties:

| Property | Knowledge Capsule | Credential |
|----------|------------------|------------|
| **Decay** | Gradual (Ebbinghaus curve) | Binary — valid or not |
| **FTS5** | Full content indexed (plaintext) | **NEVER** index secret value |
| **LLM visibility** | Always visible in search results | **NEVER** visible to LLM |
| **Access control** | Trust-level based (open/internal/private) | Tool-scoped (which tools can use it) |
| **Graph edges** | Yes — relates_to, contradicts, etc. | **No** — credentials are isolated |
| **Importance score** | Yes — composite scoring, reinforcement | No — no scoring needed |
| **Consolidation** | Yes — merge overlapping notes | No — each credential is atomic |
| **Forgetting** | Yes — archive then hard-delete | No — explicit deletion only |
| **Verification** | "Is this still accurate?" | "Has this expired?" (different check) |
| **Sharing model** | Trust-level visibility | Explicit grants with time-boxing |
| **Audit granularity** | Read/write events | Every single use |

The CME's encryption map (§27.1) makes this concrete. Capsule content is encrypted, but:
- **Titles are plaintext** (Gotcha #1) — leaks what the credential is for
- **FTS5 is plaintext** (Gotcha #2) — leaks the actual secret value
- **Graph edges are plaintext** (Gotcha #3) — leaks which services connect to which projects
- **Scores are plaintext** (Gotcha #4) — leaks which credentials matter most

Credentials need a separate store that avoids all four gotchas.

---

## 3. Why TEE Doesn't Solve This

TEE (Trusted Execution Environment) protects the **model inference** step. The LLM runs inside an encrypted enclave — nobody (not even the cloud provider) can see what the model is processing.

But credential usage is a **pipeline problem**, not a model problem:

```
User: "Charge $50 to my Stripe"
         │
    ┌────▼────────────────────────────────────┐
    │  Step 1: LLM decides to call            │
    │          stripe_checkout(amount=50)      │  ← IN TEE (model inference)
    │                                          │     TEE protects this step
    └────┬────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────┐
    │  Step 2: Python agents.py receives      │
    │          tool call from LLM             │  ← NOT IN TEE
    └────┬────────────────────────────────────┘     (runs on your pod server)
         │
    ┌────▼────────────────────────────────────┐
    │  Step 3: Python decrypts Stripe key     │
    │          from vault_secrets table       │  ← NOT IN TEE
    │          sk_live_abc123                  │     (Python process memory)
    └────┬────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────┐
    │  Step 4: Python sends HTTP POST to      │
    │          api.stripe.com                 │  ← NOT IN TEE
    │          Authorization: Bearer sk_live_ │     (network call)
    └────┬────────────────────────────────────┘
         │
    ┌────▼────────────────────────────────────┐
    │  Step 5: Response → sanitized →         │
    │          returned to LLM                │  ← IN TEE (model processes result)
    │                                          │     TEE protects this step
    └─────────────────────────────────────────┘
```

**TEE protects steps 1 and 5** — the model's thinking. The cloud provider running the LLM can't peek.

**TEE does NOT protect steps 2-4** — your Python tool execution layer, the decrypted secret in process memory, the HTTP call to the external API. These all run on **your pod server**, not in the TEE enclave.

### Where TEE Helps (and Where It Doesn't)

| Threat | TEE Protects? | What Does Protect? |
|--------|--------------|-------------------|
| Model provider reads the prompt | ✅ Yes | — |
| Prompt injection tricks LLM into outputting the key | ❌ No | Brokered pattern (key never in prompt) |
| Python process compromised, attacker reads memory | ❌ No | OS-level isolation, `secureZero` on Zig side |
| Tool call logged with credential in args | ❌ No | Never pass credential as tool argument |
| Pool member asks "what API keys does John have?" | ❌ No | Citadel credential-probe patterns |
| Attacker reads the DB file | ❌ No | AES-256-GCM encryption of secret values |

### 3.2 TEE Containers Change This (Phala, Gramine)

If the **entire pod** runs inside a TEE container (e.g., Phala Network's TEE containers, Gramine, Intel SGX), the threat model shifts dramatically:

```
┌─────────────────────────────────────────────────────┐
│  TEE Container (Phala / Gramine / SGX)              │
│                                                      │
│  Everything inside is SEALED from the cloud host:   │
│  ├── Python agents.py + tool execution    SEALED    │
│  ├── Zig kernel + libpodos.dylib          SEALED    │
│  ├── SQLite + vault_secrets table         SEALED    │
│  ├── vault_keys dict (in-memory)          SEALED    │
│  ├── HTTP calls to Stripe                 ATTESTED  │
│  └── LLM inference (if co-located)        SEALED    │
│                                                      │
│  The cloud provider hosting this container           │
│  CANNOT read process memory, DB contents,            │
│  or network traffic. Steps 2-4 are protected.        │
└─────────────────────────────────────────────────────┘
```

**TEE containers eliminate Layer 0 (infrastructure) threats entirely.** The cloud provider can't peek at Python memory, can't read the SQLite file, can't intercept the Stripe API call.

### 3.3 What TEE Containers Still DON'T Solve

Even with the entire pod in a TEE, the **agent behavior** threats remain:

| Threat | TEE Container? | What Solves It? |
|--------|---------------|-----------------|
| Cloud provider reads pod memory | ✅ Eliminated | — |
| Cloud provider reads DB file | ✅ Eliminated | — |
| Network interception | ✅ Eliminated (attested TLS) | — |
| Prompt injection → "print all API keys" | ❌ Still possible | Brokered pattern (§6) |
| Pool member asks "does John have Stripe?" | ❌ Still possible | Citadel rules (§12) |
| Agent echoes credential in conversation | ❌ Still possible | Response scrubbing (§12.3) |
| Credential expires unnoticed | ❌ Still possible | Timeline hooks (§15) |

**The brokered credentials pattern is needed regardless of TEE deployment.** TEE protects the infrastructure. The credential store protects the agent's behavior. Both are necessary — TEE for cloud deployment security, credential store for AI-native secret handling.

### 3.4 The Three-Layer Security Stack

TrustMesh's security is three independent layers, each catching what the others miss:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: PHALA TEE CONTAINERS                          │
│  "The cloud provider can't steal your secrets"          │
│                                                         │
│  Entire pod runs in a hardware-attested enclave.        │
│  The hosting provider cannot read process memory,       │
│  database contents, or network traffic. Even with       │
│  root access to the host machine.                       │
│                                                         │
│  Eliminates: infrastructure threats (Layer 0)           │
├─────────────────────────────────────────────────────────┤
│  Layer 2: CITADEL (https://trymighty.ai)                │
│  "The AI can't leak your secrets"                       │
│                                                         │
│  Mighty's Citadel is our multimodal AI security         │
│  sidecar. It scans both inputs (prompt injection        │
│  detection) and outputs (credential leak detection,     │
│  trust boundary enforcement, soft-leak patterns).       │
│  Runs as a Go sidecar or via Mighty's hosted API.       │
│                                                         │
│  Catches: credential-probe queries from pool members,   │
│  prompt injection attempts to exfiltrate secrets,       │
│  credential-shaped strings in agent responses,          │
│  trust-level-aware information boundary violations.     │
│                                                         │
│  Eliminates: agent behavior threats (Layer 3)           │
├─────────────────────────────────────────────────────────┤
│  Layer 3: CREDENTIAL STORE (this design)                │
│  "Secrets are never in the wrong place"                 │
│                                                         │
│  The brokered credentials pattern ensures secret        │
│  values never enter the LLM context at all. Even if     │
│  Citadel missed a prompt injection, there's nothing     │
│  to exfiltrate — the LLM doesn't have the secret.      │
│                                                         │
│  Handles: encrypted storage, tool-scoped access,        │
│  time-boxed sharing, rotation, expiry, usage audit.     │
│                                                         │
│  Eliminates: secret exposure by design (Layer 4)        │
└─────────────────────────────────────────────────────────┘
```

**Defense in depth**: If an attacker bypasses Phala (theoretical hardware exploit), Citadel still blocks prompt injection. If Citadel misses a novel attack, the brokered pattern means the LLM doesn't have the secret anyway. If the credential store has a bug, Citadel catches the leak in the output. No single layer failure compromises user credentials.

### 3.5 Deployment Models

```
Self-hosted pod (laptop, home server):
├── No TEE — rely on OS permissions + disk encryption
├── Citadel sidecar (local Go binary or Mighty API)
├── Credential store for brokered pattern
└── Threat model: physical access = game over (same as Vault)

Cloud pod (Phala TEE container):
├── Full TEE — cloud provider sealed out
├── Citadel inside the enclave (or Mighty API via attested TLS)
├── Credential store for brokered pattern
└── Threat model: only novel prompt injection remains
│   (and Citadel + brokered pattern mitigate that)

Hybrid (TEE model inference + regular pod server):
├── Model provider can't read prompts (TEE inference)
├── Pod server protected by OS + Citadel
├── Credential store bridges both layers
└── Stepping stone to full TEE deployment
```

---

## 4. Research: How Others Handle This

### 4.1 HashiCorp Vault — Dynamic Secrets + Transit

Vault's pattern for AI agents (validated pattern, 2025):

```
User → IdP issues JWT → Agent performs OBO token exchange
     → MCP tool layer authenticates to Vault with OBO token
     → Vault issues short-lived dynamic credential
     → Tool uses credential → credential expires
```

**What we adopt**: The principle that credentials should be short-lived and scoped to a specific operation. Version IDs in ciphertext (`v1.{nonce}.{cipher}.{tag}`) so key rotation doesn't require re-encrypting everything.

**What we skip**: The full Vault infrastructure (server, policies, HSM). We're a single-binary pod, not a cluster.

### 4.2 1Password Connect — Reference-Based Access

```python
# 1Password pattern: resolve a reference, never hold the value
secret = await client.secrets.resolve("op://vault/stripe/api-key")
# 'secret' used only in tool layer, never passed to LLM
```

**What we adopt**: The `op://` reference pattern. Our equivalent: the agent knows a credential *exists* by name but never sees the value. It says "use my Stripe credential" and the tool layer resolves it.

**What we skip**: External dependency on 1Password cloud service.

### 4.3 MCP OAuth 2.1 (November 2025 Spec)

The MCP Authorization Specification mandates OAuth 2.1 for HTTP-based MCP servers. Key properties:
- Resource Indicators (RFC 8707) bind tokens to specific servers
- Token passthrough explicitly forbidden — prevents confused deputy attacks
- STDIO transport exempt (use env var injection instead)

**Reality check**: As of 2025, 53% of MCP servers use static API keys, only 8.5% use OAuth. The spec is right but adoption is slow.

**What we adopt**: The principle that credentials should be resolved at the infrastructure layer, not by the agent. For our MCP server (`src/mcp_server.py`), credentials injected from the session, not from tool arguments.

### 4.4 Key Insight: The Brokered Credentials Pattern

Every production system converges on the same architecture:

```
LLM outputs: tool_name + tool_args (NO credentials)
         ↓
Tool execution layer: (trusted Python, NOT in LLM context)
         ↓
Credential broker: maps (user_id, tool_name) → decrypted secret
         ↓
HTTP call with injected Authorization header
         ↓
Response returned to LLM (credential NEVER in response)
```

The LLM only ever sees tool names and sanitized arguments. Credential resolution happens in infrastructure the LLM cannot address or cause to emit output.

---

## 5. Design Principles

### 5.1 The Kernel-Userspace Boundary (Same as CME)

**Zig is the kernel. The LLM is userspace.**

```
Zig Kernel (mechanical, NO vault key needed):
├── Check share expiry (compare timestamps)
├── Increment use_count
├── Check max_uses limit
├── Rate limit credential access per tool
├── Auto-expire inactive shares
└── Credential audit logging

Python Layer (vault key needed):
├── Decrypt secret value for tool injection
├── Encrypt new credential on creation
└── Scrub credential-shaped strings from tool responses

LLM (NEVER):
├── Never sees raw secret values
├── Can know a credential exists by name ("you have a Stripe key")
├── Cannot know what the value is
├── Cannot reveal credential existence to pool queries
└── Citadel blocks credential-probe patterns
```

### 5.2 Metadata vs. Secret Value Split

```
┌─────────────────────────────────────────────────┐
│  SEARCHABLE (FTS5 — credential_fts table)       │
│  Agent can see these, use them to select which   │
│  credential to use for a tool call               │
│                                                  │
│  ├── name: "Stripe Production Key"               │
│  ├── service: "stripe.com"                       │
│  └── category: "payments"                        │
├─────────────────────────────────────────────────┤
│  ENCRYPTED (AES-256-GCM — never searchable)     │
│  Only decrypted in tool execution layer          │
│  Never returned to LLM, never in FTS5           │
│                                                  │
│  ├── secret_encrypted: bytes (the actual key)    │
│  └── metadata_encrypted: bytes (2FA codes, etc.) │
└─────────────────────────────────────────────────┘
```

### 5.3 Credentials Are Isolated

No graph edges. No importance scores. No decay curves. No consolidation. Credentials exist in a separate namespace from knowledge capsules. The memory graph never learns about credentials. This prevents graph-topology leakage (CME Gotcha #3).

### 5.4 Owner-Only by Default

Credentials have a binary visibility model:
- **owner_only**: Only the credential owner's agent can see it exists (default)
- **shared**: Specific users/pools granted time-boxed access via `credential_shares`
- **NEVER open**: Credentials cannot be `open` or `internal` visibility. Period.

---

## 6. The Brokered Credentials Pattern

This is the core architecture. It defines how credentials flow from storage to external API without ever touching the LLM.

### 6.1 The Flow

```
User: "Charge $50 to my Stripe"
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  LLM (TEE or standard)                              │
│                                                      │
│  Decides: call stripe_checkout(amount=50)            │
│                                                      │
│  Note: NO credential in the tool call args.          │
│  The LLM doesn't know the Stripe key.               │
│  It just knows the tool exists and what it does.     │
└──────────────────┬──────────────────────────────────┘
                   │ tool_name="stripe_checkout"
                   │ args={"amount": 50}
                   ▼
┌─────────────────────────────────────────────────────┐
│  Python Tool Execution Layer (agents.py)             │
│                                                      │
│  1. Receive tool call from LLM                       │
│  2. Look up: does this tool need a user credential?  │
│     → Query vault_secrets WHERE owner_id=user_id     │
│       AND 'stripe_checkout' IN scoped_tools          │
│  3. Found: credential_id="cred_abc"                  │
│  4. Decrypt: secret = decrypt(secret_encrypted, vk)  │
│  5. Log: credential_ops(used, cred_abc, stripe_...)  │
│  6. Call: POST api.stripe.com/v1/charges             │
│     Header: Authorization: Bearer sk_live_abc123     │
│  7. Receive response from Stripe                     │
│  8. Scrub response (remove any credential echoes)    │
│  9. Return sanitized result to LLM                   │
│                                                      │
│  The secret exists in Python memory for steps 4-6    │
│  only. It is NEVER passed back to the LLM.           │
└──────────────────┬──────────────────────────────────┘
                   │ result={"charge_id": "ch_xyz",
                   │         "status": "succeeded"}
                   ▼
┌─────────────────────────────────────────────────────┐
│  LLM (TEE or standard)                              │
│                                                      │
│  "Done! Successfully charged $50. Charge ID: ch_xyz" │
│                                                      │
│  The LLM never knew the Stripe key.                  │
│  It only knows the operation succeeded.              │
└─────────────────────────────────────────────────────┘
```

### 6.2 What the Agent Sees vs. What It Doesn't

```python
# The agent's tool schema (visible to LLM):
{
    "name": "stripe_checkout",
    "description": "Charge a customer's card via Stripe",
    "input_schema": {
        "type": "object",
        "properties": {
            "amount": {"type": "number"},
            "currency": {"type": "string", "default": "usd"},
            "description": {"type": "string"}
        },
        "required": ["amount"]
    }
    # NO credential parameter. The LLM doesn't know it needs one.
}

# What happens internally (invisible to LLM):
async def handle_stripe_checkout(ctx: ToolContext, amount: float, **kwargs):
    # 1. Find the user's Stripe credential
    cred = await get_scoped_credential(ctx.user_id, "stripe_checkout")
    if not cred:
        return {"error": "No Stripe credential configured. Add one in Settings."}

    # 2. Decrypt (vault_key from ctx, same pattern as capsule decryption)
    api_key = decrypt(cred.secret_encrypted, ctx.vault_key)

    # 3. Audit the use
    await log_credential_use(cred.id, "stripe_checkout", ctx.user_id)

    # 4. Make the API call (secret in Authorization header only)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.stripe.com/v1/charges",
            headers={"Authorization": f"Bearer {api_key.decode()}"},
            data={"amount": int(amount * 100), "currency": kwargs.get("currency", "usd")},
        )

    # 5. Scrub and return (never include auth headers in result)
    return {"charge_id": resp.json().get("id"), "status": resp.json().get("status")}
```

### 6.3 How the Agent Knows Which Credential to Use

The agent doesn't pick credentials — the tool execution layer does. When a user stores a credential, they associate it with tool names:

```
Credential: "Stripe Production Key"
├── service: "stripe.com"
├── scoped_tools: ["stripe_checkout", "stripe_refund", "stripe_balance"]
└── secret_encrypted: <AES-256-GCM blob>
```

When `stripe_checkout` is called, the execution layer queries:
```sql
SELECT * FROM vault_secrets
WHERE owner_id = ?
  AND is_active = 1
  AND json_each.value = 'stripe_checkout'  -- scoped_tools contains this tool
```

If multiple credentials match (e.g., test vs. production), the most recently created active one wins, or the user can specify via a `credential_name` tool parameter.

---

## 7. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  Credential Store                                                     │
│                                                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────┐   │
│  │  Credential  │  │  Share       │  │  Credential Operations     │   │
│  │  Registry    │  │  Manager     │  │                            │   │
│  │              │  │              │  │  Expiry check (cron)       │   │
│  │  CRUD        │  │  Grant       │  │  Rotation reminder (cron)  │   │
│  │  Lookup      │  │  Revoke      │  │  Inactive share cleanup    │   │
│  │  Scoping     │  │  Time-box    │  │  Usage audit               │   │
│  │              │  │  Pool share  │  │                            │   │
│  └──────┬──────┘  └──────┬───────┘  └────────────┬───────────────┘   │
│         │                │                        │                   │
│  ═══════╪════════════════╪════════════════════════╪══════════════════ │
│         │         SQLite (vault_secrets + credential_shares)          │
│  ═══════╪════════════════╪════════════════════════╪══════════════════ │
│         │                │                        │                   │
│  ┌──────┴────────────────┴────────────────────────┴───────────────┐   │
│  │                    Existing Kernel                              │   │
│  │  Timeline Engine │ FTS5 │ Crypto │ Trust │ Sessions │ DB       │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ═══════════════════ C ABI (libpodos.dylib) ═══════════════════════  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │                    Python Bridge                                │   │
│  │  credential_bridge.py │ agents.py (tools) │ routes/credentials │   │
│  └────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Credential Created (user via API or agent tool)
        │
        ├──▶ Encrypt secret value (AES-256-GCM, same vault_key as capsules)
        ├──▶ Store in vault_secrets table
        ├──▶ Index name+service in credential_fts (NOT the secret value)
        ├──▶ Log credential_ops: 'created'
        └──▶ If expires_at set: create timeline entry for rotation reminder

Credential Used (tool execution layer)
        │
        ├──▶ Zig: check is_active, check share validity, check rate limit
        ├──▶ Python: decrypt secret, inject into HTTP call
        ├──▶ Zig: increment use_count, update last_used_at
        ├──▶ Zig: log credential_ops: 'used'
        └──▶ Python: scrub response, return to LLM

Credential Shared (owner grants access)
        │
        ├──▶ Create credential_shares row (time-boxed, max_uses)
        ├──▶ Zig: validate share limits (max shares per credential)
        └──▶ Log credential_ops: 'shared'

Timeline Tick (PodOS, cron-driven)
        │
        ├──▶ credential.expiry_check (daily cron)
        │       ├── Find credentials approaching expiry
        │       └── Create verification timeline entry
        │
        ├──▶ credential.share_cleanup (daily cron)
        │       ├── Expire time-boxed shares past expires_at
        │       ├── Expire shares past max_uses
        │       └── Log credential_ops: 'share_expired'
        │
        └──▶ credential.rotation_reminder (weekly cron)
                ├── Find credentials older than rotation_interval
                └── Dispatch AGENT_TASK: "Remind owner to rotate"
```

---

## 8. SQLite Schema

Three new tables, created by `db.zig` alongside existing FTS5, timeline, and CME tables:

### 8.1 vault_secrets

```sql
CREATE TABLE IF NOT EXISTS vault_secrets (
    id TEXT PRIMARY KEY,                    -- UUID
    owner_id TEXT NOT NULL,                 -- FK → users.id
    name TEXT NOT NULL,                     -- "Stripe Production Key" (searchable)
    service TEXT NOT NULL DEFAULT '',       -- "stripe.com" (searchable)
    category TEXT NOT NULL DEFAULT '',      -- "payments", "email", "development"
    secret_encrypted BLOB NOT NULL,         -- AES-256-GCM with vault_key
    metadata_encrypted BLOB,               -- Optional: 2FA codes, notes (encrypted)
    scoped_tools TEXT NOT NULL DEFAULT '[]',-- JSON array: ["stripe_checkout", "stripe_refund"]
    expires_at TEXT,                        -- ISO 8601, null = no expiry
    rotation_interval_days INTEGER,         -- Suggest rotation after N days, null = never
    is_active INTEGER NOT NULL DEFAULT 1,   -- 0 = deactivated (soft delete)
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Owner lookup (most common query)
CREATE INDEX IF NOT EXISTS idx_vault_secrets_owner
    ON vault_secrets(owner_id, is_active);

-- Tool scoping lookup (used during tool execution)
-- Note: scoped_tools is JSON, queried via json_each() in SQL
CREATE INDEX IF NOT EXISTS idx_vault_secrets_active
    ON vault_secrets(is_active) WHERE is_active = 1;
```

### 8.2 credential_shares

```sql
CREATE TABLE IF NOT EXISTS credential_shares (
    id TEXT PRIMARY KEY,                    -- UUID
    credential_id TEXT NOT NULL,            -- FK → vault_secrets.id
    grantor_id TEXT NOT NULL,               -- Must be credential owner
    grantee_id TEXT NOT NULL,               -- User ID or network ID
    grantee_type TEXT NOT NULL CHECK(grantee_type IN ('user', 'network')),
    expires_at TEXT NOT NULL,               -- MANDATORY: no permanent shares
    max_uses INTEGER,                       -- null = unlimited within time window
    use_count INTEGER NOT NULL DEFAULT 0,
    can_reshare INTEGER NOT NULL DEFAULT 0, -- 0 = cannot reshare (default)
    revoked_at TEXT,                        -- null = active, set = revoked
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Fast lookup: "what credentials can this user access?"
CREATE INDEX IF NOT EXISTS idx_credential_shares_grantee
    ON credential_shares(grantee_id, grantee_type)
    WHERE revoked_at IS NULL;

-- Fast lookup: "who has access to this credential?"
CREATE INDEX IF NOT EXISTS idx_credential_shares_credential
    ON credential_shares(credential_id)
    WHERE revoked_at IS NULL;
```

### 8.3 credential_ops (Audit)

```sql
CREATE TABLE IF NOT EXISTS credential_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credential_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN (
        'created', 'updated', 'used', 'rotated',
        'shared', 'share_revoked', 'share_expired',
        'deactivated', 'deleted'
    )),
    actor_id TEXT NOT NULL,                 -- Who performed this
    tool_name TEXT,                         -- Which tool used it (for 'used' ops)
    share_id TEXT,                          -- Which share was used (for shared access)
    details TEXT,                           -- JSON metadata
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_credential_ops_credential
    ON credential_ops(credential_id, created_at);

CREATE INDEX IF NOT EXISTS idx_credential_ops_actor
    ON credential_ops(actor_id, created_at);
```

### 8.4 credential_fts (Separate from capsule_fts)

```sql
-- SEPARATE FTS5 table. Never mixed with capsule_fts.
-- Indexes ONLY name + service + category. NEVER the secret value.
CREATE VIRTUAL TABLE IF NOT EXISTS credential_fts USING fts5(
    credential_id UNINDEXED,
    name,
    service,
    category UNINDEXED,
    tokenize='porter unicode61'
);
```

---

## 9. Credential Lifecycle

### 9.1 State Machine

Credentials have a simple linear lifecycle — no decay curves, no importance scoring:

```
created → active → [rotated] → deactivated → deleted
                      ↑ │
                      └─┘  (rotation creates new, deactivates old)
```

| State | Meaning | Searchable? | Usable? |
|-------|---------|-------------|---------|
| active | Normal operating state | Yes (credential_fts) | Yes |
| rotated | Replaced by newer version | No (removed from FTS) | No |
| deactivated | Soft-deleted by owner | No | No |
| deleted | Hard-deleted (row removed) | No | No |

### 9.2 Rotation

When a user rotates a credential:
1. Old credential: `is_active = 0`, removed from credential_fts
2. New credential: created with same name/service/scoped_tools
3. Active shares on old credential → automatically moved to new credential
4. Audit log: `credential_ops(rotated, old_id, details={new_id})`

```python
async def rotate_credential(old_id: str, new_secret: bytes, vault_key: bytes):
    old = await get_credential(old_id)

    # Create new credential with same metadata
    new_id = create_credential(
        owner_id=old.owner_id,
        name=old.name,
        service=old.service,
        scoped_tools=old.scoped_tools,
        secret=new_secret,
        vault_key=vault_key,
    )

    # Transfer active shares
    await transfer_shares(old_id, new_id)

    # Deactivate old
    await deactivate_credential(old_id)

    # Audit
    await log_credential_op(old_id, 'rotated', details={"new_id": new_id})
```

### 9.3 Expiry

Credentials with `expires_at` set trigger a timeline entry:
- 7 days before expiry: AGENT_TASK notification → "Your Stripe key expires in 7 days"
- On expiry: `is_active = 0`, all shares expired, audit logged
- The Zig kernel handles the expiry check mechanically (timestamp comparison)

---

## 10. Pool Credential Sharing

### 10.1 The Netflix Problem

Alice wants to share her Netflix login with Bob (sister) for one month.

```
Alice's pod:
    vault_secrets: {id: "cred_1", name: "Netflix", secret_encrypted: <blob>}

Alice shares:
    credential_shares: {
        credential_id: "cred_1",
        grantor_id: alice.id,
        grantee_id: bob.id,           ← Bob's user ID (or ghost user ID)
        grantee_type: "user",
        expires_at: "2026-03-17",     ← 30 days from now
        max_uses: null,               ← unlimited within window
        can_reshare: false,           ← Bob can't re-share to others
    }

Bob's agent uses it:
    1. Bob's agent calls a tool that needs Netflix auth
    2. Tool layer checks: Bob has no Netflix credential of his own
    3. Tool layer checks: any shares granted to Bob?
       → Found share from Alice, not expired, not revoked
    4. Decrypt Alice's credential using Alice's vault_key
       → Requires Alice to be logged in (vault_key in memory)
       → OR: share includes a re-encrypted copy (see §10.3)
    5. Inject into tool call
    6. Audit: credential_ops(used, cred_1, actor=bob, share_id=share_1)
```

### 10.2 Pool-Wide Sharing

For pool/network sharing (e.g., family Netflix):

```
credential_shares: {
    credential_id: "cred_1",
    grantor_id: alice.id,
    grantee_id: family_network.id,    ← Network ID
    grantee_type: "network",
    expires_at: "2026-12-31",
    max_uses: null,
    can_reshare: false,
}
```

Any member of `family_network` can use the credential through their agent. The lookup path:
1. Check user's own credentials
2. Check shares granted directly to user
3. Check shares granted to any network the user is a member of

### 10.3 The Vault Key Problem for Shares

Cross-pod sharing has a key management challenge: Bob's pod doesn't have Alice's vault_key. Options:

**Option A: Re-encrypt on share** (recommended)
When Alice creates a share, the secret is re-encrypted with Bob's vault_key and stored in the share row:
```sql
ALTER TABLE credential_shares ADD COLUMN
    secret_reencrypted BLOB;  -- Secret encrypted with grantee's vault_key
```
This means Bob's pod can decrypt independently. Alice's pod handles the re-encryption at share creation time.

**Option B: Proxy through owner's pod**
Bob's agent calls Alice's pod at share-use time. Alice's pod decrypts and proxies the API call. More secure (secret never leaves Alice's pod) but adds latency and requires Alice's pod to be online.

**Option C: Shared pool key**
Pools already have shared encryption concepts (see `federation-design.md`). Credentials shared to a pool could be encrypted with the pool key. This is the most scalable but requires pool key infrastructure.

**Recommendation**: Start with Option A for user-to-user shares. It's simple, works offline, and the re-encrypted copy is still AES-256-GCM protected. Add Option C when pool key infrastructure exists.

### 10.4 Share Limits

```
Per credential:     max 10 active shares (prevent credential sprawl)
Per user as grantee: max 50 active shares received (prevent abuse)
Per network:        max 5 credentials shared to a single network
Share duration:     max 365 days (force periodic re-authorization)
```

These are enforced by the Zig kernel at share creation time.

---

## 11. Encryption Boundaries

Following the CME's encryption map pattern (§27):

```
┌──────────────────────────────────────────────────────────────────┐
│                    trustmesh.db (SQLite)                           │
│                                                                   │
│  ┌── ENCRYPTED (AES-256-GCM with vault_key) ──────────────────┐  │
│  │                                                              │  │
│  │  vault_secrets.secret_encrypted        ◄── THE SECRET       │  │
│  │  vault_secrets.metadata_encrypted      ◄── EXTRA METADATA   │  │
│  │  credential_shares.secret_reencrypted  ◄── SHARE COPY       │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌── PLAINTEXT (readable without vault_key) ───────────────────┐  │
│  │                                                              │  │
│  │  vault_secrets.name                  ◄── Leak: service name │  │
│  │  vault_secrets.service               ◄── Leak: domain       │  │
│  │  vault_secrets.scoped_tools          ◄── Leak: tool names   │  │
│  │  vault_secrets.use_count             ◄── Leak: usage freq   │  │
│  │  vault_secrets.last_used_at          ◄── Leak: usage timing │  │
│  │                                                              │  │
│  │  credential_fts (name + service)     ◄── Same as above      │  │
│  │                                                              │  │
│  │  credential_shares                   ◄── Leak: who shared   │  │
│  │  credential_ops                      ◄── Leak: usage audit  │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Plaintext Exposure Analysis

| Field | What leaks | Mitigation |
|-------|-----------|------------|
| name | "Stripe Production Key" | Attacker knows you use Stripe. Acceptable — same threat level as capsule titles. |
| service | "stripe.com" | Same as above. |
| scoped_tools | ["stripe_checkout"] | Attacker knows which tools are configured. Low risk — tool names are public. |
| use_count / last_used_at | Usage patterns | Temporal analysis possible. 90-day retention on credential_ops. |
| credential_shares | Who has access to what | Attacker can map sharing relationships. Mitigated by OS file permissions. |

**Key property**: The actual secret value (API key, password, token) is ALWAYS encrypted. An attacker with DB file access knows you use Stripe but cannot extract your API key.

**Future improvement**: Encrypt `name` and `service` as well (like capsule content). This would require encrypted FTS5 or blind index (hash-based lookup). Research area — same as CME's "Encrypted FTS5" future note.

---

## 12. Citadel Integration

### 12.1 New Credential-Probe Patterns

Add to `citadel.py` OUTPUT_RISK_PATTERNS:

```python
"credential_probe": [
    # Direct existence queries
    r"(?i)(does|do)\s+\w+\s+have\s+(access|credentials?|logins?|accounts?|api\s*keys?|passwords?)",
    r"(?i)what\s+(services?|accounts?|logins?|credentials?|api\s*keys?)\s+does\s+\w+\s+have",
    r"(?i)list\s+\w+'?s?\s+(credentials?|accounts?|logins?|api\s*keys?)",

    # Indirect probing
    r"(?i)(which|what)\s+(payment|banking|cloud|social)\s+(services?|platforms?)\s+(does|do|is)\s+\w+",
    r"(?i)can\s+\w+\s+(access|connect\s+to|log\s*in\s+to)\s+\w+",

    # Credential value extraction attempts
    r"(?i)(show|display|print|output|reveal|tell\s+me)\s+(the\s+)?(api\s*key|password|token|secret|credential)",
    r"(?i)what\s+is\s+(the|my|their)\s+(api\s*key|password|token|secret)",
],

"credential_value_in_output": [
    # Detect credential-shaped strings in agent responses
    r"sk_live_[a-zA-Z0-9]{20,}",          # Stripe live keys
    r"sk_test_[a-zA-Z0-9]{20,}",          # Stripe test keys
    r"ghp_[a-zA-Z0-9]{36,}",             # GitHub PATs
    r"gho_[a-zA-Z0-9]{36,}",             # GitHub OAuth
    r"AKIA[A-Z0-9]{16}",                  # AWS access keys
    r"(?i)bearer\s+[a-zA-Z0-9\-_.]{20,}", # Generic bearer tokens
    r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY", # Private keys
],
```

### 12.2 Agent System Prompt Additions

Add to `CROSS_QUERY_SYSTEM_PROMPT` and `build_trust_context()`:

```
CREDENTIAL BOUNDARIES (absolute, never override):
- NEVER reveal whether any user has credentials for any service
- NEVER confirm or deny the existence of API keys, passwords, or logins
- NEVER mention credential sharing arrangements
- If asked about someone's service access, respond: "I can't share information about
  credential configurations."
- This applies at ALL trust levels, including private. Credential existence is
  owner-only information.
```

### 12.3 Response Scrubbing

After every tool call that uses a credential, scan the response:

```python
def scrub_credential_patterns(response: str) -> str:
    """Remove credential-shaped strings from tool responses before returning to LLM."""
    patterns = [
        (r'sk_live_[a-zA-Z0-9]+', '[REDACTED_STRIPE_KEY]'),
        (r'sk_test_[a-zA-Z0-9]+', '[REDACTED_STRIPE_TEST_KEY]'),
        (r'ghp_[a-zA-Z0-9]+', '[REDACTED_GITHUB_PAT]'),
        (r'AKIA[A-Z0-9]{16}', '[REDACTED_AWS_KEY]'),
        (r'(?i)(bearer\s+)[a-zA-Z0-9\-_.]{20,}', r'\1[REDACTED_TOKEN]'),
        (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----.*?-----END', '[REDACTED_PRIVATE_KEY]'),
    ]
    for pattern, replacement in patterns:
        response = re.sub(pattern, replacement, response, flags=re.DOTALL)
    return response
```

---

## 13. Zig Kernel Modules

### 13.1 Module Map

```
kernel/src/
├── credential.zig     # ~250 LOC — CRUD, lookup, scoping, share validation
└── credential_ops.zig # ~150 LOC — Expiry sweep, share cleanup, audit

kernel/tests/
├── test_credential.zig     # ~200 LOC
└── test_credential_ops.zig # ~150 LOC
```

### 13.2 C ABI Exports

```zig
// ═══════════════════════════════════════════
//  CREDENTIAL STORE
// ═══════════════════════════════════════════

/// Create a new credential (encrypted secret stored as blob)
export fn podos_credential_create(
    db_handle: ?*anyopaque,
    id: [*]const u8, id_len: u32,
    owner_id: [*]const u8, owner_len: u32,
    name: [*]const u8, name_len: u32,
    service: [*]const u8, service_len: u32,
    category: [*]const u8, category_len: u32,
    secret_encrypted: [*]const u8, secret_len: u32,
    scoped_tools_json: [*]const u8, tools_len: u32,
    expires_at: [*]const u8, expires_len: u32,  // empty = no expiry
) callconv(.c) i32;

/// Look up credential by owner + tool name (for brokered pattern)
export fn podos_credential_for_tool(
    db_handle: ?*anyopaque,
    owner_id: [*]const u8, owner_len: u32,
    tool_name: [*]const u8, tool_len: u32,
    out: [*]u8, out_capacity: u32, out_len: *u32,
) callconv(.c) i32;  // Returns JSON: {id, name, service, secret_encrypted_b64}

/// List credentials for an owner (metadata only, no secrets)
export fn podos_credential_list(
    db_handle: ?*anyopaque,
    owner_id: [*]const u8, owner_len: u32,
    out: [*]u8, out_capacity: u32, out_len: *u32,
) callconv(.c) i32;  // Returns JSON array

/// Deactivate a credential
export fn podos_credential_deactivate(
    db_handle: ?*anyopaque,
    id: [*]const u8, id_len: u32,
    owner_id: [*]const u8, owner_len: u32,  // Must be owner
) callconv(.c) i32;

/// Record credential use (increment count, update last_used_at, log op)
export fn podos_credential_record_use(
    db_handle: ?*anyopaque,
    credential_id: [*]const u8, cred_len: u32,
    actor_id: [*]const u8, actor_len: u32,
    tool_name: [*]const u8, tool_len: u32,
    share_id: [*]const u8, share_len: u32,  // empty if direct use
) callconv(.c) i32;

// ═══════════════════════════════════════════
//  CREDENTIAL SHARES
// ═══════════════════════════════════════════

/// Create a share (time-boxed, validated by Zig)
export fn podos_credential_share_create(
    db_handle: ?*anyopaque,
    id: [*]const u8, id_len: u32,
    credential_id: [*]const u8, cred_len: u32,
    grantor_id: [*]const u8, grantor_len: u32,
    grantee_id: [*]const u8, grantee_len: u32,
    grantee_type: [*]const u8, type_len: u32,  // "user" or "network"
    expires_at: [*]const u8, expires_len: u32,
    max_uses: i32,  // -1 = unlimited
    secret_reencrypted: [*]const u8, reenc_len: u32,
) callconv(.c) i32;

/// Check if a user has a valid share for a credential
export fn podos_credential_share_check(
    db_handle: ?*anyopaque,
    credential_id: [*]const u8, cred_len: u32,
    grantee_id: [*]const u8, grantee_len: u32,
    out: [*]u8, out_capacity: u32, out_len: *u32,
) callconv(.c) i32;  // Returns JSON share details or empty

/// Revoke a share
export fn podos_credential_share_revoke(
    db_handle: ?*anyopaque,
    share_id: [*]const u8, share_len: u32,
    grantor_id: [*]const u8, grantor_len: u32,  // Must be grantor
) callconv(.c) i32;

/// Sweep expired shares (called by timeline cron)
export fn podos_credential_sweep_expired(
    db_handle: ?*anyopaque,
) callconv(.c) i32;  // Returns count of expired shares cleaned

/// Sweep expired credentials (called by timeline cron)
export fn podos_credential_sweep_expiry(
    db_handle: ?*anyopaque,
) callconv(.c) i32;  // Returns count of expired credentials deactivated
```

---

## 14. Python Bridge & Agent Integration

### 14.1 credential_bridge.py

```python
"""Python bridge to Zig credential store via ctypes."""

import ctypes
import json
from src.crypto import encrypt, decrypt

def create_credential(owner_id: str, name: str, service: str,
                      secret: bytes, vault_key: bytes,
                      scoped_tools: list[str], **kwargs) -> str:
    """Encrypt secret and store credential."""
    cred_id = str(uuid4())
    secret_encrypted = encrypt(secret, vault_key)

    _lib.podos_credential_create(
        _db_handle,
        cred_id.encode(), len(cred_id),
        owner_id.encode(), len(owner_id),
        name.encode(), len(name),
        service.encode(), len(service),
        kwargs.get("category", "").encode(), len(kwargs.get("category", "")),
        secret_encrypted, len(secret_encrypted),
        json.dumps(scoped_tools).encode(), ...,
        kwargs.get("expires_at", "").encode(), ...,
    )

    # Index in credential_fts (name + service only, NEVER the secret)
    _lib.podos_fts_upsert(...)  # Uses credential_fts table

    return cred_id


def get_credential_for_tool(user_id: str, tool_name: str) -> dict | None:
    """Look up credential by tool scope. Returns metadata + encrypted blob."""
    out = ctypes.create_string_buffer(65536)
    out_len = ctypes.c_uint32()
    rc = _lib.podos_credential_for_tool(
        _db_handle,
        user_id.encode(), len(user_id),
        tool_name.encode(), len(tool_name),
        out, 65536, ctypes.byref(out_len),
    )
    if rc != 0 or out_len.value == 0:
        return None
    return json.loads(out[:out_len.value])


def use_credential(credential_id: str, vault_key: bytes,
                   tool_name: str, actor_id: str,
                   share_id: str = "") -> bytes:
    """Decrypt and return secret, logging the use. Caller must clear after use."""
    # Record use in Zig (audit + increment count)
    _lib.podos_credential_record_use(
        _db_handle,
        credential_id.encode(), len(credential_id),
        actor_id.encode(), len(actor_id),
        tool_name.encode(), len(tool_name),
        share_id.encode(), len(share_id),
    )

    # Decrypt in Python (needs vault_key)
    cred = get_credential_for_tool(...)
    return decrypt(bytes.fromhex(cred["secret_encrypted_hex"]), vault_key)
```

### 14.2 Tool Execution Integration (agents.py)

```python
async def execute_tool_with_credentials(ctx: ToolContext, tool_name: str, args: dict):
    """Wrap tool execution with credential injection."""
    from src.credential_bridge import get_credential_for_tool, use_credential

    # 1. Check if this tool has a scoped credential
    cred = get_credential_for_tool(ctx.user_id, tool_name)

    if cred:
        # 2. Decrypt (vault_key from context)
        raw_secret = use_credential(
            cred["id"], ctx.vault_key, tool_name, ctx.user_id
        )

        # 3. Inject into tool args (internal key, never returned to LLM)
        args["_credential"] = raw_secret

    # 4. Execute the tool
    result = await TOOL_HANDLERS[tool_name](ctx, **args)

    # 5. Remove credential from args (defensive)
    args.pop("_credential", None)

    # 6. Scrub response
    if isinstance(result, str):
        result = scrub_credential_patterns(result)

    return result
```

---

## 15. Timeline Integration

Following the CME pattern — credential operations are timeline entries, not separate daemons:

### 15.1 Credential Expiry Check

```python
engine.create_entry(
    label="Credential Expiry Check",
    category="system",
    stream="private",
    salience=0.1,
    trigger_type="cron",
    trigger_cron="0 6 * * *",  # Daily at 6am
    hook_type="SYSTEM",
    hook_prompt="credential_expiry_check",
)
```

When fired, the Zig kernel runs `podos_credential_sweep_expiry()`:
- Deactivates credentials past `expires_at`
- Logs `credential_ops(deactivated, ...)`
- For credentials expiring within 7 days: creates an AGENT_TASK timeline entry to notify owner

### 15.2 Share Cleanup

```python
engine.create_entry(
    label="Credential Share Cleanup",
    category="system",
    stream="private",
    salience=0.1,
    trigger_type="cron",
    trigger_cron="0 6 * * *",  # Daily at 6am (same sweep window)
    hook_type="SYSTEM",
    hook_prompt="credential_share_cleanup",
)
```

Runs `podos_credential_sweep_expired()`:
- Expires shares past `expires_at`
- Expires shares past `max_uses`
- Logs `credential_ops(share_expired, ...)`

### 15.3 Rotation Reminder

```python
engine.create_entry(
    label="Credential Rotation Reminder",
    category="system",
    stream="private",
    salience=0.2,
    trigger_type="cron",
    trigger_cron="0 9 * * 1",  # Weekly, Monday 9am
    hook_type="AGENT_TASK",
    hook_prompt="Check for credentials that should be rotated. "
                "Look for credentials older than their rotation_interval_days. "
                "Notify the owner with specific instructions for each service.",
)
```

---

## 16. Agent Tools

Two new tools for the agent, added to `agents.py`:

### 16.1 list_credentials (metadata only)

```python
{
    "name": "list_credentials",
    "description": "List your stored credentials (names and services only, never secret values). "
                   "Use this to check if you have a credential for a service before asking the user to provide one.",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Filter by service domain (optional)"},
            "category": {"type": "string", "description": "Filter by category (optional)"},
        }
    }
}
```

Returns: `[{"name": "Stripe Key", "service": "stripe.com", "scoped_tools": [...], "expires_at": "..."}]`

**Never returns**: The actual secret value.

### 16.2 manage_credential

```python
{
    "name": "manage_credential",
    "description": "Store, update, or delete a credential. The secret value will be encrypted "
                   "and never shown in conversations. Specify which tools can use this credential.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["store", "rotate", "deactivate"]},
            "name": {"type": "string"},
            "service": {"type": "string"},
            "secret": {"type": "string", "description": "The API key, password, or token"},
            "scoped_tools": {"type": "array", "items": {"type": "string"}},
            "category": {"type": "string"},
            "credential_id": {"type": "string", "description": "For rotate/deactivate actions"},
        },
        "required": ["action"]
    }
}
```

**Critical**: When the agent calls `manage_credential(action="store", secret="sk_live_...")`, the secret passes through the LLM context exactly once — at creation time, from the user's message. After that, it is encrypted and never returned to the LLM. The agent should immediately respond with "Stored your Stripe credential securely" and never echo the key.

The agent prompt should include:
```
CREDENTIAL HANDLING:
- When a user provides a credential (API key, password, token), use manage_credential
  to store it immediately.
- NEVER repeat the credential value in your response. Say "Stored securely" instead.
- NEVER include credential values in save_capsule — use manage_credential.
- When a tool call fails due to missing credentials, suggest storing one.
```

---

## 17. API Routes

New file: `src/routes/credentials.py`

```python
router = APIRouter(prefix="/api/credentials", tags=["credentials"])

# CRUD
POST   /api/credentials/              # Create credential
GET    /api/credentials/              # List own credentials (metadata only)
GET    /api/credentials/{id}          # Get credential metadata
DELETE /api/credentials/{id}          # Deactivate credential
POST   /api/credentials/{id}/rotate   # Rotate credential

# Shares
POST   /api/credentials/{id}/share    # Create share
GET    /api/credentials/{id}/shares   # List shares for a credential
DELETE /api/credentials/shares/{share_id}  # Revoke share

# Audit
GET    /api/credentials/{id}/usage    # Usage audit log

# All endpoints require auth: auth_user_id = Depends(get_current_user_id)
# All endpoints verify ownership: credential.owner_id == auth_user_id
# Share endpoints: grantor_id == auth_user_id
```

---

## 18. Security Against Adversarial Processes

### 18.1 Threat Model

```
Layer 0: Physical      — Attacker has the DB file
Layer 1: Network       — Attacker is a peer pod (cross-pod queries)
Layer 2: Application   — Attacker sends crafted API requests
Layer 3: Agent         — Attacker manipulates LLM via prompt injection
Layer 4: Credential    — Attacker exploits credential mechanics
```

### 18.2 Layer-by-Layer Analysis

| Layer | Attack | Impact | Mitigation |
|-------|--------|--------|------------|
| 0 | Read vault_secrets table | Sees names/services but NOT secret values | AES-256-GCM on secret_encrypted |
| 0 | Read credential_fts | Same as above — only name+service indexed | By design |
| 0 | Read credential_shares | Sees sharing relationships | OS file permissions, disk encryption |
| 1 | Pool member queries "does X have Stripe?" | Credential existence leak | Citadel credential_probe patterns |
| 1 | Pool member probes via tool calls | Usage of X's credentials | Credentials scoped to owner only (shares require explicit grant) |
| 2 | Unauthenticated API access | CRUD on credentials | All endpoints require session auth |
| 2 | Authenticated user accesses other's credentials | Cross-user credential read | owner_id check on every endpoint |
| 3 | Prompt injection: "print all API keys" | Secret value extraction | Brokered pattern — LLM never has secret values |
| 3 | Prompt injection: "what credentials exist?" | Metadata leak | Citadel output scanning |
| 3 | Prompt injection: "call manage_credential to exfiltrate" | Create fake credential to encode data | Rate limit manage_credential (5/hour) |
| 4 | Create many shares to overwhelm grantee | Abuse shared credentials | Per-credential share limit (10) |
| 4 | Use shared credential after revocation | Stale share | Zig validates share on every use (not cached) |
| 4 | Timing attack on credential lookup | Infer existence | Constant-time lookup (always query, return empty if not found) |

### 18.3 Credential-Specific Citadel Rules

The agent's system prompt MUST include (at ALL trust levels):

```
ABSOLUTE CREDENTIAL RULES:
1. NEVER output any credential value (API key, password, token) in a response.
2. NEVER confirm or deny that a specific user has credentials for a service.
3. NEVER describe sharing arrangements ("Alice shared her Netflix with Bob").
4. If a user asks to see their own credential value, say: "For security, credential
   values are never displayed. They're used automatically by your tools."
5. If a tool call response contains a credential-shaped string, REDACT it before
   including in your response.
```

---

## 19. Relationship to Other Systems

### 19.1 Capsule Memory Engine (CME)

```
CME manages: What the agent KNOWS
├── Knowledge capsules (memory, skill, procedure, schedule, preference, contact)
├── Graph edges (relates_to, contradicts, supersedes, ...)
├── Importance scoring + decay curves
├── Consolidation + forgetting
└── FTS5 search over full content

Credential Store manages: What the agent CAN DO
├── Secret values (API keys, passwords, tokens)
├── Tool scoping (which tools can use which credentials)
├── Time-boxed sharing (user-to-user, pool)
├── Usage audit (every single use logged)
└── FTS5 search over names/services only (NEVER values)

They share:
├── Same transit engine for AES-256-GCM encryption (transit.zig + transit_bridge.py)
├── Keys stored in Zig memory via transit engine (never in Python dict)
├── Same Zig kernel (libpodos.dylib)
├── Same SQLite database (trustmesh.db)
├── Same timeline for cron-driven operations
├── Same C ABI pattern for Python FFI
└── Same db.zig for table creation

They do NOT share:
├── FTS5 tables (capsule_fts vs credential_fts)
├── Audit tables (memory_ops vs credential_ops)
├── Lifecycle models (decay vs binary active/inactive)
├── Access control (trust-level vs tool-scoped)
└── LLM visibility (searchable vs never-visible)
```

### 19.2 Personal Data Schema

The `personal-data-schema.md` defines structured fields for factual data (diet, allergies, employer). Credentials are a natural extension:

```
Personal Data
├── SELF (identity & preferences)
├── HEALTH (allergies, medications)
├── WORK (employer, team)
├── ...
└── CREDENTIALS                           ← NEW category
    ├── payments: [{service: "stripe.com", name: "Production Key"}]
    ├── development: [{service: "github.com", name: "Personal PAT"}]
    ├── email: [{service: "smtp.gmail.com", name: "App Password"}]
    └── entertainment: [{service: "netflix.com", name: "Family Plan"}]
```

The structured field for credentials stores **metadata only** — the actual secret values live in `vault_secrets`. This lets the personal data schema provide quick lookups ("what services do I use?") without exposing secret material.

### 19.3 PodOS Timeline

All credential lifecycle operations use the existing PodOS timeline hook system:

| Operation | hook_type | Zig or Python? |
|-----------|-----------|----------------|
| Expiry sweep | SYSTEM | Zig only (timestamp comparison) |
| Share cleanup | SYSTEM | Zig only (timestamp + count comparison) |
| Rotation reminder | AGENT_TASK | Python dispatches to agent |
| Expiry notification | AGENT_TASK | Python dispatches to agent |

### 19.4 Vault Architecture (from VAULT_QUICK_REFERENCE.md)

| Vault Concept | Credential Store Equivalent |
|---------------|---------------------------|
| KV Engine | vault_secrets table |
| Transit Engine | `transit.zig` + `transit_bridge.py` (keys in Zig memory, never Python) |
| Policies (deny-by-default) | scoped_tools + owner-only default |
| Audit Logging (fail-safe) | credential_ops table |
| Leases (parent-child cascade) | credential_shares (time-boxed, revocable) |
| Key Rotation | rotate endpoint (transfer shares to new credential) |
| Seal/Unseal | Transit engine lifecycle (login → key stored in Zig, logout → secureZero) |
| Citadel (Sentinel equivalent) | [Mighty Citadel](https://trymighty.ai) — policy-as-scanning for AI outputs |

---

## 20. Implementation Plan

### 20.1 Build Order

| Step | What | Where | LOC est | Depends on |
|------|------|-------|---------|------------|
| **1** | SQLite tables (vault_secrets, credential_shares, credential_ops, credential_fts) | `db.zig` | ~60 | — |
| **2** | Credential CRUD module | `credential.zig` | ~250 | Step 1 |
| **3** | Share validation module | `credential.zig` (same file) | ~150 | Step 1 |
| **4** | Expiry + share sweep module | `credential_ops.zig` | ~150 | Steps 2, 3 |
| **5** | C ABI exports in main.zig | `main.zig` | ~100 | Steps 2, 3, 4 |
| **6** | Zig tests | `test_credential.zig`, `test_credential_ops.zig` | ~350 | Steps 2, 3, 4 |
| **7** | Python bridge | `credential_bridge.py` | ~120 | Step 5 |
| **8** | API routes | `routes/credentials.py` | ~200 | Step 7 |
| **9** | Tool execution integration (brokered pattern) | `agents.py` | ~80 | Step 7 |
| **10** | Agent tools (list_credentials, manage_credential) | `agents.py` | ~60 | Step 7 |
| **11** | Citadel patterns (credential_probe, value scrubbing) | `citadel.py` | ~40 | — |
| **12** | Timeline entries (expiry, share cleanup, rotation) | `seed.py` | ~30 | Step 7 |
| **13** | Response scrubbing (credential patterns in tool output) | `agents.py` | ~30 | — |
| **14** | Python integration tests | `tests/test_credentials.py` | ~300 | All above |
| **15** | Seed data: demo credentials for test scenarios | `seed.py` | ~50 | Steps 7, 8 |

### 20.2 Estimated Totals

| Language | New LOC | Files |
|----------|---------|-------|
| Zig (kernel) | ~710 | 2 source + 2 test |
| Python (bridge + routes + tools) | ~910 | 4 source + 1 test |
| **Total** | **~1,620** | **9 files** |

### 20.3 C ABI Export Count

Current: 95 exports (timeline 48 + FTS5 6 + crypto 14 + trust 1 + session 9 + rate_limit 7 + db 2 + memory graph/score/ops ~8)
New: +12 exports (credential CRUD 4 + share 4 + sweep 2 + audit 2)
**Total: ~107 exports**

### 20.4 Estimated Effort

| Phase | Hours | Description |
|-------|-------|-------------|
| Zig kernel (steps 1-6) | 6h | Tables, CRUD, shares, sweeps, tests |
| Python bridge + routes (steps 7-8) | 4h | ctypes bridge, REST endpoints |
| Agent integration (steps 9-13) | 4h | Brokered pattern, tools, Citadel, scrubbing |
| Tests + seed (steps 14-15) | 3h | Integration tests, demo data |
| **Total** | **~17h** | |

---

## 21. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **FTS5 indexes secret value by accident** | Full credential exposure in plaintext | credential_fts is a separate table, only name+service. Code review: grep for `credential` in `fts.zig` to ensure separation. |
| **Agent echoes credential in response** | Secret in conversation history | Citadel output scanning + scrub_credential_patterns() + prompt instructions |
| **Vault key unavailable for shared credential** | Share unusable | Re-encrypt secret with grantee's vault_key at share creation (Option A) |
| **Credential sprawl** | Too many stored, hard to manage | Agent periodic review via timeline AGENT_TASK: "You have 23 credentials, 8 unused in 90 days. Deactivate?" |
| **Share time-bomb** | Shares outlive intent | Mandatory expires_at, max 365 days. No permanent shares. |
| **Cross-pod share complexity** | Ghost user vault key management | Start with same-pod shares only. Cross-pod via re-encryption in Phase 2. |
| **Memory leak of decrypted secrets** | Secret persists in Python memory | Use `del secret` + `ctypes.memset` after tool call. Zig side: `secureZero` on all buffers. |
| **Tool call logging** | Credential in observability traces | `_credential` key stripped from args before any logging. Tool handlers never log this key. |

---

## Appendix: Glossary

| Term | Definition |
|------|-----------|
| **Brokered credential** | Pattern where credentials are resolved at the infrastructure layer, never by the LLM |
| **Credential** | A secret value (API key, password, token) used to authenticate with an external service |
| **credential_fts** | Separate FTS5 table for credential metadata search (name + service only) |
| **Scoped tools** | List of tool names a credential is authorized to be used with |
| **Share** | Time-boxed grant allowing another user or pool to use a credential |
| **vault_secrets** | SQLite table storing encrypted credentials (distinct from knowledge_capsules) |

---

Generated: 2026-02-17
Context: Credential store design for TrustMesh AI agents
Sources: HashiCorp Vault patterns, 1Password Connect, MCP OAuth 2.1 spec, CME architecture
Related: `capsule-memory-engine.md` (§27 encryption map), `VAULT_QUICK_REFERENCE.md`, `personal-data-schema.md`
