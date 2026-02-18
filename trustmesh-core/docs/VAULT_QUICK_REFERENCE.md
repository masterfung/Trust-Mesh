# Vault → TrustMesh Quick Reference Card

## Core Vault Primitives (One-Pager)

```
┌─────────────────────────────────────────────────────────────┐
│ VAULT ARCHITECTURE (3 Systems)                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Client (speaks REST API)                                    │
│   ├─ Authenticates via auth method (OIDC, AppRole, etc)    │
│   ├─ Receives token                                        │
│   └─ Makes requests: GET /secret/data/foo                  │
│                                                             │
│ Server (responds to API)                                    │
│   ├─ Validates token (policy attached)                     │
│   ├─ Policy engine: can_access(path, capability)           │
│   ├─ Encrypts/decrypts secrets                             │
│   ├─ Audit logs all requests (fail-safe)                   │
│   └─ Manages leases (TTL, renewal, cascade revoke)         │
│                                                             │
│ Storage Backend (untrusted)                                │
│   ├─ Encrypted at rest (AES-256-GCM)                       │
│   ├─ No logic; just KV store                               │
│   └─ Vault doesn't trust it (can be compromised)           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Seal/Unseal: Key Hierarchy

```
┌──────────────────────────────┐
│ Physical Storage             │
│ (encrypted ciphertexts)      │
└──────────────────────────────┘
         ↓ [SEALED STATE]
┌──────────────────────────────┐
│ Barrier Layer (encryption)   │
│ Needs: root_key              │
└──────────────────────────────┘
         ↓ [Unsealing ceremony]
┌──────────────────────────────┐
│ Root Key (in-memory)         │
│ Constructed from:            │
│ - Shamir shares (3-of-5), or │
│ - HSM decrypt, or            │
│ - KMS auto-unseal            │
└──────────────────────────────┘
         ↓
┌──────────────────────────────┐
│ Keyring (multiple keys)      │
│ - Data encryption key        │
│ - Auth token key             │
│ - Lease key                  │
└──────────────────────────────┘
         ↓
┌──────────────────────────────┐
│ Data Encryption (AES-256-GCM)│
│ [UNSEALED STATE]             │
└──────────────────────────────┘
```

**TrustMesh Mapping**:
- Root key ← Pod master key (derived from admin ceremony)
- Keyring ← vault_keys dict (per-user/agent encryption keys)
- Barrier ← SQLite + Zig kernel (storage abstraction)

---

## Secrets Engines: Independent Mount Points

```
Vault Mounts (each independent):

/secret (KV v2)               /transit                /aws
├─ Read secret ✓             ├─ Encrypt ✓            ├─ GetRole ✓
├─ Write secret ✓            ├─ Decrypt ✓            ├─ GetDynCreds ✓
├─ Soft delete ✓             ├─ Rotate key ✓        └─ Revoke ✓
└─ Versioning ✓              └─ HMAC ✓

Separate policies per engine:
path "secret/*" {
  capabilities = ["read", "list"]
}
path "transit/encrypt/app" {
  capabilities = ["update"]
}
path "aws/creds/prod" {
  capabilities = ["read"]
}
```

**TrustMesh Mapping**:
```
/capsule (KV v2 equiv)        /timeline (DynSec equiv)  /transit
├─ Read capsule               ├─ Create entry           ├─ Encrypt
├─ Create/update              ├─ Execute entry          ├─ Decrypt
├─ List versions              ├─ Revoke entry (cascade) └─ Rotate
└─ Rollback                   └─ Status
```

---

## Policies: Path + Capability Matrix

```
VAULT POLICY MODEL (Deny-by-Default)

┌─────────────────────────────────────┐
│ path "secret/foo" {                 │
│   capabilities = ["read"]           │
│ }                                   │
└─────────────────────────────────────┘

Path Matching (3 types):
  1. Exact:   "secret/foo"        → only "secret/foo"
  2. Glob:    "secret/*"          → "secret/foo", "secret/bar"
  3. Segment: "secret/+/password" → "secret/x/password" (one segment)

Capabilities (tied to HTTP):
  read         (GET)
  create/write (POST/PUT)
  delete       (DELETE)
  list         (LIST)
  patch        (PATCH)
  sudo         (root-protected)
  deny         (explicit block, highest priority)

Example Policy:
```
path "secret/*" {
  capabilities = ["read", "list"]
}

path "secret/admin/*" {
  capabilities = ["deny"]  # Block all, even if parent allows
}

path "database/creds/prod" {
  capabilities = ["read"]
  required_parameters = ["role"]
}
```
```

**TrustMesh Mapping**:
```
Trust Level ← Capabilities:
  open       ← ["read", "list"]
  internal   ← ["read", "list", "update"]
  private    ← ["read", "list", "update", "delete", "execute"]

Category filtering ← Path matching:
  "capsule/health/*"
  "capsule/finance/+/tax-return"
  "timeline/entries/daily_checkin"
```

---

## Audit Logging: Fail-Safe Guarantee

```
VAULT AUDIT DEVICES (≥1 must succeed)

┌──────────────┐         ┌──────────────┐
│  File Audit  │         │  Syslog      │
│  (local)     │         │  (remote)    │
└──────────────┘         └──────────────┘
       ↓                         ↓
       ├─────────┬──────────────┤
               ↓
        Vault Request

        IF audit_device_1.write() FAILS:
          IF audit_device_2.write() SUCCEEDS: ✓ Continue
          ELSE: ✗ REFUSE REQUEST (fail-safe)

        IF both fail: ✗ REFUSE REQUEST

Audit Entry (JSON):
{
  "time": "2026-02-17T12:34:56Z",
  "auth": {"client_token": "...", "display_name": "app-1"},
  "request": {"operation": "read", "path": "secret/db"},
  "response": {"data": {...}},
  "error": null,
  "request_id": "...",
  "remote_address": "10.0.0.1"
}
```

**TrustMesh Mapping**:
```
Mandatory AuditDevice (fail-safe):
┌────────────────────────────────────┐
│ SQLite WAL (append-only)           │
│ ├─ timestamp, agent_id, operation  │
│ ├─ resource_id, trust_level        │
│ ├─ result (allowed/denied/error)   │
│ ├─ reason (why denied?)            │
│ └─ citadel_risk (safe/warn/blocked)│
└────────────────────────────────────┘

IF audit.insert() fails:
  ✗ ABORT request, don't decrypt capsule
```

---

## Leases: Parent-Child Hierarchy + Renewal

```
VAULT LEASE LIFECYCLE

Agent Lease (24h, renewable=true)
│
├─ Task 1 Lease (5min, parent=Agent)
│  ├─ Capsule Read Token (1min, parent=Task1)
│  └─ Capsule Write Token (1min, parent=Task1)
│     [Task1 expires → both child tokens revoked]
│
└─ Task 2 Lease (5min, parent=Agent)

If Agent Lease expires:
  ├─ Task 1 revoked (+ children cascade)
  └─ Task 2 revoked (+ children cascade)

Token Renewal (Periodic):
  ┌──────────────┐
  │ Token (30d)  │
  │ renewable=T  │
  └──────────────┘
         ↓ (agent calls /renew)
  ┌──────────────┐
  │ Token (30d)  │  Renewed counter = 2
  │ exp_time += 30d
  └──────────────┘
         ↓ (no renew for 7d)
  ┌──────────────┐
  │ Token REVOKED│
  └──────────────┘
```

**TrustMesh Mapping**:
```python
class UCANToken:
    id: str
    exp_time: float
    parent_token_id: Optional[str]  # For cascade
    renewable: bool                 # Can renew?
    last_renewed_at: Optional[float]
    renewal_count: int

# Agent pulse check
async def revoke_stale_tokens():
    for token in db.query(UCANToken).filter(
        last_renewed_at < now - 24h  # No heartbeat for 24h
    ):
        await revoke_token_cascade(token.id)
        await notify_admin(f"Agent {token.subject} auto-paused")
```

---

## Transit Engine: Encryption-as-a-Service

```
VAULT TRANSIT (Keys stay at Vault)

Application (doesn't hold keys):
  ├─ POST /transit/encrypt
  │  ├─ plaintext: "secret data"
  │  └─ → ciphertext: "v1.nonce.tag.cipher"
  │
  ├─ POST /transit/decrypt
  │  ├─ ciphertext: "v1.nonce.tag.cipher"
  │  └─ → plaintext: "secret data"
  │
  └─ POST /transit/rotate (Admin)
     ├─ Generate new key (v2)
     ├─ Old ciphertexts still decrypt with v1
     └─ Next encrypt uses v2 (embedded in output)

Key Versioning:
  Ciphertext format: v{version}.{encrypted_payload}
  On decrypt: parse version, use corresponding key
  No re-encryption needed on rotate
```

**TrustMesh Mapping**:
```python
@router.post("/api/transit/encrypt")
async def encrypt(plaintext: str, agent_id: str):
    key = await get_vault_key(agent_id)
    version = await get_key_version(agent_id)
    ciphertext = aes_encrypt(plaintext, key)
    return {"ciphertext": f"v{version}.{ciphertext}"}

@router.post("/api/transit/decrypt")
async def decrypt(ciphertext: str, agent_id: str):
    version = int(ciphertext.split(".")[0][1:])
    key = await get_vault_key_version(agent_id, version)
    plaintext = aes_decrypt(ciphertext[5:], key)  # Skip "vN."
    return {"plaintext": plaintext}

@router.post("/api/transit/rotate")
async def rotate(agent_id: str):
    # Generate new key, store as v{version+1}
    # Re-encrypt all capsules owned by agent
    # Audit log the rotation
```

---

## Enterprise Features Worth Stealing

```
1. NAMESPACES (Multi-Tenancy)
   ├─ Org A Namespace (policies, auth methods isolated)
   ├─ Org B Namespace (separate policies, auth methods)
   └─ Cross-namespace access: controlled via parent policies

2. SENTINEL (Policy-as-Code)
   ├─ Conditional policies (time, source IP, etc)
   ├─ Audit triggers (log access + send Slack alert)
   └─ Enforcement levels (advisory, soft-mandatory, hard-mandatory)

3. REPLICATION (HA + DR)
   ├─ Performance replication (read replicas, fast failover)
   ├─ DR replication (full backup, manual failover)
   └─ Delta sync (only changed data transmitted)

4. HSM INTEGRATION (FIPS 140-2)
   ├─ Master key never leaves HSM
   ├─ Auto-unseal (HSM decrypts master key on startup)
   └─ Entropy augmentation (RNG from HSM)
```

---

## Threat Model Summary

**Vault In-Scope** (defends against):
- Eavesdropping (TLS)
- Data tampering (AES-GCM)
- Unauthorized access (ACL checks)
- Lack of accountability (audit logs)
- Secret confidentiality (encryption)
- High availability (replication)

**Vault Out-of-Scope** (doesn't defend):
- Storage backend compromise
- Memory analysis of running process
- Host-level code execution
- Malicious admin configuration
- Compromised client tokens

**TrustMesh Additions**:
- **In-Scope**: Agent compromise detection (rate limiting, anomaly detection)
- **In-Scope**: Cross-pod DID spoofing defense (signature verification)
- **In-Scope**: Trust context leakage (Citadel output scanning)

---

## Implementation Priority Matrix

```
Priority  Feature                    Impact   Effort   Timeline
─────────────────────────────────────────────────────────────────
1         Mandatory Audit Logging    HIGH     6h       Day 1
2         Cascade Revocation         HIGH     4h       Day 1
3         Pod Unsealing Ceremony     HIGH     8h       Day 2
4         Policy Engine (Zig)        MEDIUM   10h      Day 3-4
5         Transit Engine             MEDIUM   5h       Day 2
6         Token Renewal + Monitor    MEDIUM   4h       Day 2
7         Audit Export               LOW      4h       Day 5 (nice-to-have)
8         Pod Replication            LOW      8h       Phase 2

MVP (Security): Priority 1 + 2 → ~10 hours (1 day)
Full Implementation: All 8 → ~50 hours (2.5 weeks)
```

---

## File Reference

**Vault Architecture Docs** (this repo):
- `docs/vault-architecture-mapping.md` — Full 2500-line deep dive
- `docs/vault-vs-trustmesh-comparison.md` — Side-by-side comparison
- `docs/vault-implementation-priorities.md` — Implementation roadmap + code examples

**External References**:
- [Vault Docs](https://developer.hashicorp.com/vault/docs)
- [Vault API](https://developer.hashicorp.com/vault/api-docs)
- [Vault Security Model](https://developer.hashicorp.com/vault/docs/internals/security)
- [HCP Vault Pricing](https://cloud.hashicorp.com/products/vault/pricing)

---

## One-Liner Mappings (Copy-Paste Reference)

```python
# Vault → TrustMesh

Seal/Unseal      → Pod initialization ceremony (Shamir 3-of-5 + HSM wrap)
KV Engine        → Capsule store (versioning, soft delete, rollback)
Transit Engine   → /api/transit/encrypt,decrypt,rotate
Policies         → Path matching + deny-by-default (Zig kernel)
Audit Logging    → Immutable SQLite WAL (fail-safe)
Leases           → UCAN tokens (parent-child cascade, renewal)
Namespaces       → Pod isolation (federation-aware namespaces future)
Sentinel         → Temporal policies (cron conditions, rate limits)
Replication      → Pod replication (delta sync, failover)
HSM Integration  → Master key seal wrap (FIPS 140-2)
```

---

## Gotchas & Common Mistakes

**Don't**:
- ✗ Forget fail-safe audit (if audit fails, refuse operation)
- ✗ Hardcode policies (use HCL parser, compile to Zig)
- ✗ Skip parent-child relationships in tokens (cascade revocation is critical)
- ✗ Use in-memory dicts for keys (use HSM/TPM when possible)
- ✗ Emit explicit "allowed" before audit (log first, then return)

**Do**:
- ✓ Audit before returning (fail-safe)
- ✓ Cascade revocation (parent → children)
- ✓ Embed key version in ciphertext (no re-encryption on rotate)
- ✓ Deny-by-default (empty policy = no access)
- ✓ Fail fast on trust violations (refuse > log after decryption)

---

## Quick Start Template

```python
# 1. Create AuditDevice (Priority 1)
class AuditEvent:
    timestamp: float
    agent_id: str
    operation: str
    resource_id: str
    trust_level: str
    result: str  # "allowed", "denied", "error"
    reason: str

class AuditDevice:
    async def log_event(self, event: AuditEvent):
        # Append to SQLite
        # Raise if I/O fails (fail-safe)

# 2. Cascade Revocation (Priority 2)
class UCANToken:
    parent_token_id: Optional[str]
    children = relationship(...)

async def revoke_token_cascade(token_id):
    for child in token.children:
        await revoke_token_cascade(child.id)

# 3. Transit Engine (Priority 5)
@router.post("/api/transit/encrypt")
async def encrypt(plaintext: str, agent_id: str):
    key = vault_keys[agent_id]
    ciphertext = aes_gcm_encrypt(plaintext, key)
    return {"ciphertext": f"v1.{ciphertext}"}

# Done. Ship.
```

---

Generated: 2026-02-17
Context: HashiCorp Vault vs. TrustMesh architecture mapping
Source: Research synthesis + Vault documentation
