# HashiCorp Vault Architecture & AI-Native Vault Mapping

## Executive Summary
HashiCorp Vault is a secrets management platform built on four core pillars: seal/unseal (key ceremony), secrets engines (modular storage), policies (deny-by-default ACLs), and audit logging (tamper-evident). Enterprise features add namespaces (multi-tenancy), Sentinel (policy-as-code), replication (HA/DR), and HSM integration. The pricing shift from per-secret to per-client (HCP Vault Secrets → HCP Vault Dedicated, June 2026) signals that Vault serves primarily as operational infrastructure, not per-transaction consumption.

For AI-native vaults, the mapping is structural, not algorithmic. Vault's compartmentalization, immutable audit trails, and trust boundaries directly translate to agent architectures, but AI requires additions Vault lacks: semantic search over encrypted data, granular trust-based sharing (not just ACLs), agent identity (DIDs vs tokens), and temporal execution (agent scheduling).

---

## Vault Core Primitives

### 1. Seal/Unseal: Master Key Ceremony

**Vault's Implementation:**
- **Sealed State**: On startup, Vault accesses physical storage but cannot decrypt data
- **Key Hierarchy**: Data encryption key (keyring) ← root key ← unseal key
- **Shamir Secret Sharing**: Default unseal splits root key into shares (threshold reconstruction)
- **Auto-Unseal Alternatives**:
  - Transit Seal: Use Vault's own Transit engine recursively
  - KMS/HSM: Delegate to AWS KMS, HashiCorp Cloud KMS, or hardware HSMs
  - Recovery Keys: When using HSM/KMS, operators get recovery keys instead of unseal shards

**Architecture Pattern**:
```
Storage (encrypted)
    ↓
Physical Backend (untrusted)
    ↓
Barrier (encryption layer)
    ↓
[Sealed] ─→ [Unseal Ceremony] ─→ [Unsealed]
           (Shamir/KMS/HSM)
    ↓
Root Key (in-memory only)
    ↓
Keyring (multiple encryption keys)
    ↓
Data Encryption (AES-256-GCM)
```

**TrustMesh Translation (PodOS Timeline Kernel)**:
- Pod startup = unseal ceremony (master key ceremony)
- `pod_id + master_key` = identity (analogous to root key)
- Vault keys dict = keyring (agent/capsule encryption keys derived per-user)
- SQLite FTS5 + Zig kernel = physical backend (now with timeline + semantic search)
- Agent initialization = unseal ritual (DID proof + vault key derivation)

**Key Innovation for AI**:
- Pod could support **graduated unsealing**: read-only mode (no temporal execution), full unsealing (agent tasks enabled)
- Example: Pod operator can query existing capsules before agents begin task automation
- Requires root key split between "pod identity" (unsealed immediately) and "agent authority" (requires ceremony for task execution)

---

### 2. Secrets Engines: Modular Storage & Generation

**Vault's Secrets Engines**:
- **KV v1/v2**: Static secret storage (read/write/list)
- **Dynamic Secrets**: Generate temporary credentials (AWS IAM, PostgreSQL, etc.)
- **Transit**: Encryption-as-a-service (encrypt/decrypt/rotate operations)
- **PKI**: Certificate generation and revocation
- **Database**: Manage DB credentials with automatic rotation
- **SSH**: SSH OTP or CA-based key signing

**Key Property**: Each engine operates at a mount path (e.g., `secret/`, `transit/`, `aws/`) with independent policies and lifetime.

**TrustMesh Translation**:
- KV v2 → **Capsule store** (versioning, soft delete, rollback)
- Transit → **Encryption bridge** (agent data in-flight, client-side encryption tooling)
- PKI → **Agent identity (DIDs)** — certificate-like but ed25519-based with trust metadata
- Dynamic Secrets → **Time-gated capsule access** (expiring read tokens for agents, auto-revoke on task completion)
- SSH → **Agent tool invocation tokens** (agent asks permission, gets scoped tool token, revokes after use)

**Implementation Pattern**:
```python
# Capsule = hybrid KV v2 + metadata
class Capsule(Base):
    id, owner_id, content_encrypted, title
    created_at, updated_at, archived_at
    category, trust_level, ttl_expires_at
    version (for soft-delete rollback)

# Timeline Events = mini-transactions in transit engine
# Each agent task = temporary credential (UCAN token with expiry)
```

---

### 3. Policies: Deny-by-Default ACLs

**Vault Policy Model**:
```hcl
# Default: deny all
path "secret/*" {
  capabilities = ["read", "list"]
}

# Specific wildcard rules
path "secret/dept/+/password" {
  capabilities = ["read"]  # Can read secret/dept/eng/password, secret/dept/sales/password
}

# Segment matching with constraints
path "database/creds/prod" {
  capabilities = ["read"]
  required_parameters = ["role"]
}

# Explicit deny (highest priority)
path "secret/admin/*" {
  capabilities = ["deny"]
}
```

**Path Matching Priority**:
1. Exact matches beat wildcard
2. Longer paths beat shorter (specificity)
3. `deny` always wins

**TrustMesh Mapping**:
- Trust levels (open/internal/private) → capability sets
  - `open` → read (public capsules)
  - `internal` → read + list (network members)
  - `private` → all (owner + shared agents)
- UCAN token scope → required_parameters
- Category filtering → path-like segmentation (`capsule/health/*`, `capsule/finance/*`)

**Key Insight**: Vault policies are **static** (declared at mount time). AI vaults need **dynamic policy attachment** because trust context arrives at query time (e.g., "this agent is asking from a different pod").

---

### 4. Audit Logging: Tamper-Evident Records

**Vault Audit Devices**:
- File-based, syslog, socket outputs
- **Guarantee**: Write to ≥1 device or refuse the operation (fail-safe)
- **Format**: JSON logs with request/response bodies, authentication method, client token, remote address

**Audit Log Entry Structure**:
```json
{
  "time": "2026-02-17T12:34:56Z",
  "type": "request",
  "auth": {"client_token": "...", "display_name": "user@pod", "policies": ["default"]},
  "request": {"operation": "read", "path": "secret/db", "data": {...}},
  "response": {"data": {...}},
  "error": null,
  "request_id": "...",
  "remote_address": "10.0.0.1"
}
```

**Compliance Properties**:
- Immutable (append-only to file/syslog)
- Tamper-evident (HMAC or digital signature possible)
- Accessible for analysis (JSON queryable)
- Meets HIPAA, SOC2, PCI-DSS audit trail requirements

**TrustMesh Translation**:
- Audit = immutable agent query log (already in design: `pods table.logs` column)
- Add structured logging: agent_id, tool_invoked, capsule_accessed, trust_decision, timestamp
- Citadel scanning results → audit trail (risk patterns detected)
- Leverage existing SQLite WAL (write-ahead logging) for durability

**Vault's Guarantee**: Application to TrustMesh—if audit device fails, pod refuses agent requests (safe fail). Currently optional; make mandatory for federated pods.

---

### 5. Leases & TTLs: Automatic Revocation

**Vault Lease Model**:
```
create_secret() → Lease(id, ttl=30d, renewable=true)
                  ↓
                  (client renews every 7d)
                  ↓
                  (or lease expires, secret revoked)
```

**Lease Hierarchy**:
- Parent lease revoked → all children revoked
- Enables cascading cleanup (revoke token → revoke all its dynamic credentials)

**Token Lifecycle**:
- Batch tokens: No persistence, no memory footprint, high volume friendly
- Periodic tokens: Require active renewal (prove continued access)
- Orphan tokens: No parent, survives parent revocation

**TrustMesh Translation**:
- Capsule TTL (already implemented: `ttl_expires_at`) → auto-archive on expiry
- UCAN tokens ← leases (agent task tokens with built-in TTL, cascade on agent pause)
- Periodic renewal = agent heartbeat (every N minutes, prove still active)
- Batch tokens = ephemeral tool invocations (search query, one-shot answer, auto-revoke)

**Design Pattern**:
```python
# In timeline.zig or Python bridge
class TemporaryAccess:
    agent_id: str
    capsule_id: str
    expires_at: float  # Unix timestamp
    renewable: bool
    parent_token_id: str  # cascade revocation

# Revoke parent → cascade
async def revoke_agent_token(agent_id):
    token = await get_token(agent_id)
    for child in token.children:
        await revoke_token(child)  # cascade
```

---

### 6. Transit Engine: Encryption-as-a-Service

**Vault Transit**:
- Centralized encryption/decryption operations
- Key rotation without re-encrypting data (versioned key IDs in ciphertext)
- HMAC, signing, hashing operations
- Automatic key versioning and deprecation policies

**Use Case**: Application doesn't hold encryption keys; Vault holds them. Apps send plaintext to `/transit/encrypt`, receive ciphertext. Decrypt requires `/transit/decrypt`.

**TrustMesh Translation**:
- Bridge pattern: **Python agent handlers encrypt/decrypt via Zig kernel**
  - Agent asks for tool (e.g., search): send plaintext query
  - Zig kernel: encrypt with agent's key, create ephemeral token
  - Return scoped transit token + ciphertext
  - Agent can only decrypt what their token permits
- Use for multi-agent scenarios (Pod A agent queries Pod B capsule)

**Implementation**:
```python
# In agents.py tools
async def search_capsules_encrypted(query: str, agent_id: str):
    # Zig kernel has agent's encryption key
    encrypted_query = await transit_encrypt(query, agent_id)
    token = await issue_transit_token(agent_id,
                                     scope=["capsule/*"],
                                     ttl_seconds=60)
    return {"encrypted_query": encrypted_query, "token": token}
```

---

## Vault Enterprise Features: Multi-Tenancy & Scale

### 1. Namespaces

**Vault Enterprise**: Logical isolation with separate policies, auth methods, secrets engines per namespace.

```hcl
namespace "engineering/" {
  policies = ["eng-policy"]
  auth_methods = ["approle", "oidc"]
}

namespace "finance/" {
  policies = ["finance-policy"]
  auth_methods = ["ldap"]
}
```

**TrustMesh Translation**:
- Pod federation already has this: **per-pod isolation** (separate SQLite DBs, separate agent pools)
- Multi-pod scenario: `Namespace ← Pod`, `Secrets Engine ← User/Organization`, `Policies ← Trust Level`
- Extend design: **Pool namespace** (federated pods in a trust pool share a namespace)

```python
# Future design
class PodNamespace:
    id: str  # "eng-team-pool"
    pool_id: str  # ForeignKey to Network/pool
    policies: List[str]  # UCAN scopes
    shared_categories: Set[str]  # which capsule categories visible
    encryption_key: bytes  # pool-wide key (optional)
```

---

### 2. Sentinel: Policy-as-Code

**Enterprise**: Conditional policies, audit triggers, enforcement levels (advisory, soft-mandatory, hard-mandatory).

```sentinel
# Only allow access during business hours
import "time"

main = rule {
  time.now.hour >= 9 and time.now.hour <= 17
}
```

**TrustMesh Translation**:
- Already use UCAN scopes for role-based rules
- Extend: **Temporal policies** (time-based access, scheduled agent tasks)
  - Example: "Agent task can only run between 8-9 AM"
  - Implemented in PodOS Timeline Kernel: entry cron expressions, entry state machine

```python
# Timeline entry with policy
entry = EntryBuilder()
    .event_type(EntryEventType.AGENT_TASK)
    .cron("0 8 * * *")  # Run at 8 AM every day
    .action("health_check")
    .permissions(["health/*"])  # Sentinel-like scope
    .build()
```

---

### 3. Replication: HA + DR

**Performance Replication**: Read replicas, failover capability
**DR Replication**: Full backup cluster, manual failover

**Raft consensus** coordinates cluster state.

**TrustMesh Translation**:
- Already have federation (peer discovery, cross-pod queries)
- Add: **Pod replication**
  - Primary pod: writes, agent tasks
  - Replica pod: reads only (or read-heavy queries), agent task results
  - Sync mechanism: SQLite replication via WAL shipping or delta sync

**Design Idea**:
```python
# In pod.py routes
@router.post("/api/pod/replicate")
async def sync_replica(sync_token: str, since_version: int):
    # Replica pod asks: "Give me all changes since version N"
    # Primary returns: capsule updates, audit logs, pool membership changes
    # Replica applies atomically
    return await get_delta_since(since_version)
```

---

### 4. HSM Integration & Seal Wrap

**Auto-Unseal**: Master key encrypted by HSM, reconstructed on startup without operator intervention.
**FIPS Compliance**: HSM-stored keys satisfy FIPS 140-2 requirements.
**Entropy Augmentation**: External RNG from HSM.

**TrustMesh Translation**:
- Pod deployed in high-security environment (e.g., hospital server room):
  - Master key split between `software (Shamir 3-of-5)` and `HSM-backed recovery key`
  - HSM seal wrap: Pod master key encrypted by HSM before storage
  - Auto-unseal: Pod startup connects to HSM (via network or local module), retrieves key
- Implementation: Call HSM via PKCS#11 or vendor API (e.g., AWS CloudHSM, Thales Luna)

**For Zig kernel**:
```zig
// In kernel/src/main.zig
pub export fn podos_unseal_with_hsm(
    hsm_uri: [*:0]const u8,
    recovery_key: [*]const u8,
    recovery_key_len: usize,
    out_master_key: [*]u8,
) callconv(.c) i32 {
    // Call HSM via PKCS#11
    // Decrypt master_key_encrypted with recovery_key
    // Return master_key
}
```

---

## Vault API Surface: How Clients Interact

### REST HTTP API

**Endpoints**:
- `GET /v1/secret/data/foo` → read
- `POST /v1/secret/data/foo` → create
- `PUT /v1/secret/data/foo` → update
- `DELETE /v1/secret/data/foo` → delete
- `LIST /v1/secret/metadata` → list versions
- `POST /v1/auth/token/create` → create token

**Authentication**:
```bash
curl -H "X-Vault-Token: $(vault print token)" \
     https://vault.example.com:8200/v1/secret/data/foo
```

**Response**:
```json
{
  "request_id": "...",
  "lease_id": "secret/data/foo",
  "lease_duration": 0,
  "renewable": false,
  "data": {
    "data": {"password": "secret123"},
    "metadata": {"version": 3, "created_time": "..."}
  },
  "warnings": null,
  "auth": null
}
```

### CLI Wrapper

```bash
vault login -method=ldap username=user
vault kv put secret/db username=admin password=secret
vault lease revoke secret/data/db
vault policy read eng-policy
```

**CLI is thin wrapper** over HTTP API (all logic in server).

### SDKs & Libraries

- Go (official, beta)
- Python (`hvac` community library, most used)
- .NET (official, beta)
- Java, Rust, Node.js (community)

### Vault Agent Sidecar

**Vault Agent**:
- Runs alongside application
- Handles token renewal automatically
- Template rendering (inject secrets into config files)
- Auto-auth (periodically re-authenticate)

```hcl
# vault-agent.hcl
vault {
  address = "http://vault.example.com:8200"
}

auto_auth {
  method {
    type = "approle"
    config = {
      role_id_file_path = "/etc/vault/role-id"
      secret_id_file_path = "/etc/vault/secret-id"
    }
  }
}

cache {
  use_auto_auth_token = true
}

listener "unix" {
  address = "/tmp/vault.sock"
}
```

**TrustMesh Translation**:
- `trustmesh-core` = Vault server
- `mcp_server.py` (CLI + MCP) = Vault Agent equivalent
  - Handles session renewal
  - Caches auth tokens
  - Provides local socket for agent tool calls

---

## Vault Threat Model: In-Scope vs Out-of-Scope

### In-Scope Threats (Vault Defends)

1. **Eavesdropping**: TLS 1.2+ for all client-server traffic, mutually-authenticated TLS for cluster members
2. **Data Tampering**: AES-256-GCM authenticated encryption at rest
3. **Unauthorized Access**: ACL on every operation, token validation
4. **Lack of Accountability**: Audit logging with tamper-evident properties
5. **Secret Confidentiality**: All data at rest encrypted
6. **Availability**: HA configurations, replication, fault tolerance

### Out-of-Scope Threats (Vault Does NOT Defend)

1. **Storage Backend Compromise**: If attacker controls `/mnt/vault/data/`, they win. Vault doesn't defend this (it's below the barrier).
2. **Secret Existence Disclosure**: Encrypted data on disk reveals that secrets exist, even if content is hidden.
3. **Memory Analysis**: If attacker can inspect running Vault process memory, they can extract keys.
4. **Host Code Execution**: Compromised OS kernel or malicious plugin can access plaintext secrets.
5. **Malicious Configuration**: Admin who intentionally creates bad policies can grant unauthorized access.
6. **Compromised Clients**: If client token is stolen, attacker inherits that client's access level.
7. **External System Vulnerabilities**: If Vault delegates to PostgreSQL and PostgreSQL is compromised, Vault's protection ends.

### Trust Boundaries

```
┌─────────────────────────────────────┐
│      TRUSTED SYSTEMS                │
├─────────────────────────────────────┤
│ TLS endpoints (verified)            │
│ Vault server process (isolated)     │
│ HSM/KMS providers (bonded)          │
│ Audit devices (remote syslog)       │
└─────────────────────────────────────┘
           ↓ No Trust Below ↓
┌─────────────────────────────────────┐
│     UNTRUSTED SYSTEMS               │
├─────────────────────────────────────┤
│ Physical storage backend            │
│ Client machines                     │
│ Network infrastructure              │
│ Third-party plugins                 │
└─────────────────────────────────────┘
```

### TrustMesh Threat Model Extension

**What TrustMesh adds**:
1. **Agent Compromise** (NEW): If agent is compromised, it can query capsules within its trust level. Mitigations:
   - Sandbox agents (run in restricted containers)
   - Rate limit queries per agent
   - Monitor agent behavior (statistical anomalies)

2. **Cross-Pod DID Spoofing** (NEW): Attacker pretends to be agent from Pod A while on Pod B.
   - **Defense**: Agent card verification (fetch from well-known endpoint)
   - **Defense**: Signature verification on all cross-pod requests (ed25519)

3. **Trust Context Leakage** (NEW): Public trust queries inadvertently reveal organizational structure.
   - **Defense**: Citadel output scanning (soft-leak patterns)
   - **Defense**: Minimal information for public trust (only capsule metadata, no names)

**What remains out-of-scope**:
- Pod hardware compromise (USB theft, cold boot attacks)
- Zig kernel memory analysis (if attacker can dump kernel process)
- SQLite WAL tampering (if attacker has file system write access)
- Agent model extraction (if attacker runs inference on agent outputs)

---

## Actionable Architecture Mapping: AI-Native Vault

### Pattern 1: Seal/Unseal → Pod Initialization Ceremony

**Current TrustMesh**:
```python
# In seed.py
vault_keys[user_id] = derive_key(password, salt)
```

**Problem**: Vault keys loaded in plain Python dict, vulnerable to memory inspection.

**Solution**: Three-tier unsealing
```python
# Phase 1: Pod Operator Unsealing (immediate)
# - Pod starts, admin provides master_key_recovery_secret
# - Pod reconstructs pod_master_key (Shamir 3-of-5)
# - Pod can now read **metadata only** (no agent task execution)

async def unseal_pod_metadata(recovery_shares: List[str]) -> bytes:
    master_key = shamir_reconstruct(recovery_shares)
    store_in_hsm_or_tpm(master_key)  # Hardware-backed
    return master_key

# Phase 2: Agent Authority Unsealing (delayed)
# - Operator invokes a separate ceremony: authorize agents
# - System generates UCAN tokens for each agent (scoped, TTL 24h)
# - Only then can agents execute tasks, query capsules
# - This separation allows audit/review before agents activate

async def unseal_agent_authority(admin_approval: str):
    # Requires additional authentication step
    vault_keys[agent_id] = derive_key_from_ceremony(admin_approval)

# Phase 3: Execution Unsealing (per-task)
# - Agent requests capsule access
# - System verifies trust context, UCAN scope, rate limits
# - Issues ephemeral transit token (5-min TTL)
# - Agent task executes with limited-scope token
```

**Implementation in Zig**:
```zig
pub const PodSealState = enum {
    sealed,
    metadata_unsealed,
    agent_authority_unsealed,
    fully_operational,
};

pub export fn podos_unseal_step(
    phase: u32,  // 1=metadata, 2=agents, 3=execution
    secret: [*:0]const u8,
) callconv(.c) i32 {
    // return 0 on success, -1 if phase requirements not met
}
```

---

### Pattern 2: Secrets Engines → Capsule Store + Timeline

**Current**:
- Capsule model in `models.py`
- Timeline events in `timeline.zig`
- No unified "engine" concept

**Redesign**:
```python
# Capsule Store Engine (= Vault KV v2)
class CapsuleEngine:
    """Mount path: /capsule"""
    async def read(capsule_id, user_id) -> EncryptedCapsule:
        """GET /api/capsule/{capsule_id}"""

    async def create(title, content, category, user_id) -> Capsule:
        """POST /api/capsule"""

    async def list_versions(capsule_id, user_id) -> List[Version]:
        """LIST /api/capsule/{capsule_id}/versions"""

    async def rollback(capsule_id, version, user_id) -> Capsule:
        """POST /api/capsule/{capsule_id}/rollback?version={v}"""

# Timeline Engine (= Vault Transit + Dynamic Secrets)
class TimelineEngine:
    """Mount path: /timeline"""
    async def create_entry(pod_id, action, cron, permissions) -> Entry:
        """POST /api/timeline/entries"""
        # Creates a temporary credential for agent execution
        # TTL = (next cron - now) or max 24h

    async def execute_entry(entry_id, agent_id) -> Result:
        """POST /api/timeline/entries/{entry_id}/execute"""
        # Renews agent's transit token for this execution
        # Increments entry state machine (dormant→pending→active→...)

    async def revoke_entry(entry_id) -> None:
        """DELETE /api/timeline/entries/{entry_id}"""
        # Cascades: revokes all child task tokens

# Trust Engine (= Vault Transit for cross-pod)
class TrustEngine:
    """Mount path: /trust"""
    async def issue_cross_pod_token(source_agent_did, target_pod, scopes) -> Token:
        """POST /api/trust/token"""
        # Issues UCAN token for agent from Pod A to query Pod B
        # Encrypted with target pod's public key

    async def verify_cross_pod_request(token, source_did) -> Trust:
        """POST /api/trust/verify"""
        # Decrypt token, verify signature, resolve trust level
```

**API Routes** (consistent with Vault REST):
```
POST   /api/capsule                  # create
GET    /api/capsule/{id}             # read
PUT    /api/capsule/{id}             # update
DELETE /api/capsule/{id}             # delete
LIST   /api/capsule                  # list metadata
GET    /api/capsule/{id}/versions    # list versions
POST   /api/capsule/{id}/rollback    # revert

POST   /api/timeline/entries         # create task entry
GET    /api/timeline/entries/{id}    # read
POST   /api/timeline/entries/{id}/execute  # execute
DELETE /api/timeline/entries/{id}    # revoke (cascade)
LIST   /api/timeline/entries         # list
```

---

### Pattern 3: Policies → Trust + UCAN

**Current**:
- Trust levels (open/internal/private)
- UCAN tokens with scopes
- Per-query trust resolution

**Redesign as Policy Engine**:
```python
# HCL-like policy language (or JSON)
"""
# Capsule access policy
path "capsule/health/*" {
    capabilities = ["read"]
    required_parameters = ["agent_id"]
    # Only if trust_level >= "internal"
}

# Timeline execution policy
path "timeline/entries/daily_checkin" {
    capabilities = ["execute"]
    condition = "cron_schedule == '0 9 * * *'"  # Only at 9 AM
    max_requests_per_day = 1
}

# Transit token policy
path "trust/token/cross_pod" {
    capabilities = ["issue"]
    required_parameters = ["source_pod", "target_pod"]
    ttl_seconds = 300  # 5 minutes
}
"""

# Compiled into Zig-based policy checker
class PolicyEngine:
    async def can_agent_read_capsule(
        agent_id: str,
        capsule_id: str,
        trust_level: str,
    ) -> bool:
        # Check policies against agent identity, capsule category, trust context
        pass
```

---

### Pattern 4: Audit Logging → Immutable Agent Query Log

**Current**:
- Optional agent query logging
- No tamper-evident guarantee

**Redesign**:
```python
# Mandatory audit device
class AuditDevice:
    """
    Fail-safe: If audit write fails, REFUSE the operation.
    """
    async def log_event(event: AuditEvent) -> None:
        """
        Append to immutable log (SQLite WAL or file)
        Fail if I/O error.
        """
        pass

@dataclass
class AuditEvent:
    timestamp: float
    agent_id: str
    operation: str  # "read_capsule", "execute_task", "issue_token"
    resource_id: str  # capsule_id, entry_id
    trust_level: str
    result: str  # "allowed", "denied", "error"
    reason: str  # why allowed or denied
    request_context: dict  # from_pod, auth_method, etc.
    citadel_risk: str  # "safe", "warning", "blocked"

# Implementation
async def read_capsule_with_audit(capsule_id, agent_id, trust_level):
    try:
        capsule = await db.get_capsule(capsule_id)
        allowed = await policy_engine.can_read(agent_id, capsule_id, trust_level)

        if allowed:
            result = "allowed"
        else:
            result = "denied"

        # Log BEFORE returning (fail-safe)
        await audit_device.log_event(AuditEvent(
            timestamp=time.time(),
            agent_id=agent_id,
            operation="read_capsule",
            resource_id=capsule_id,
            trust_level=trust_level,
            result=result,
            reason="...",
            request_context={...},
            citadel_risk="safe",
        ))

        if allowed:
            return capsule
        else:
            raise PermissionError("Access denied")
    except Exception as e:
        # CRITICAL: Log error and refuse operation
        await audit_device.log_event(AuditEvent(..., result="error", reason=str(e)))
        raise
```

**Storage**: SQLite table `audit_log` with compound index (agent_id, timestamp) for fast queries.

---

### Pattern 5: Leases & TTLs → Timeline + Token Lifecycle

**Current**:
- UCAN tokens have exp_time
- Capsules have ttl_expires_at (optional)
- No cascade revocation

**Redesign**:
```python
# Lease = UCAN token with parent reference
class Lease:
    id: str  # "lease-agent-abc-task-123"
    parent_lease_id: Optional[str]  # For cascade
    holder: str  # agent_id or user_id
    ttl_seconds: int
    renewable: bool
    created_at: float
    expires_at: float
    resources: List[str]  # [capsule_id_1, capsule_id_2]

# Example: Agent lifecycle
"""
1. Create agent lease (24h TTL)
   lease_agent_1 = Lease(holder="agent-1", ttl=86400, renewable=True)

2. Agent executes task (creates child lease, 5min TTL)
   lease_task = Lease(parent=lease_agent_1.id, ttl=300, renewable=False)

3. Task accesses capsule (inherits task lease permissions)
   capsule_access = Lease(parent=lease_task.id, ttl=60, renewable=False)

4. Task completes
   revoke(lease_task) → cascade revoke(capsule_access)

5. Agent paused (admin revokes agent lease)
   revoke(lease_agent_1) → cascade revoke(lease_task), revoke(capsule_access)
"""

class LeaseManager:
    async def create_lease(holder, ttl, parent=None, resources=None) -> Lease:
        lease = Lease(...)
        await db.insert_lease(lease)
        return lease

    async def renew_lease(lease_id) -> Lease:
        lease = await db.get_lease(lease_id)
        if not lease.renewable:
            raise ValueError("Not renewable")
        lease.expires_at = time.time() + lease.ttl_seconds
        await db.update_lease(lease)
        return lease

    async def revoke_lease(lease_id) -> None:
        lease = await db.get_lease(lease_id)
        # Cascade: revoke all children
        children = await db.get_leases(parent_lease_id=lease_id)
        for child in children:
            await revoke_lease(child.id)
        # Mark revoked
        await db.delete_lease(lease_id)
        # Event: emit revoke event for agent shutdown
        await timeline_engine.emit_event(RevokeLease(lease_id))
```

---

### Pattern 6: Transit Engine → Multi-Agent Encryption

**Current**:
- Agent holds its own vault_key (in memory dict)
- Capsule content encrypted server-side
- No per-query key derivation

**Redesign as Transit**:
```python
# Transit endpoint: encrypt/decrypt under agent's key
@router.post("/api/transit/encrypt")
async def transit_encrypt(
    plaintext: str,
    agent_id: str,
    mount: str = "capsule",  # e.g., "capsule", "timeline"
    auth_token: str = Depends(get_current_token),
):
    """
    Encrypt plaintext under agent_id's vault key.
    Returns ciphertext with versioned key ID embedded.
    """
    vault_key = await get_vault_key(agent_id)
    ciphertext = aes_gcm_encrypt(plaintext, vault_key)
    # Embed version: ciphertext_v{key_version}.{nonce}.{tag}.{cipher}
    return {"ciphertext": ciphertext, "key_version": 1}

@router.post("/api/transit/decrypt")
async def transit_decrypt(
    ciphertext: str,
    agent_id: str,
    auth_token: str = Depends(get_current_token),
):
    """
    Decrypt ciphertext under agent_id's vault key.
    Requires agent_id matches token scope.
    """
    vault_key = await get_vault_key(agent_id)
    plaintext = aes_gcm_decrypt(ciphertext, vault_key)
    return {"plaintext": plaintext}

@router.post("/api/transit/rotate")
async def transit_rotate(
    agent_id: str,
    auth_token: str = Depends(get_current_admin),
):
    """
    Rotate agent's vault key (e.g., after compromise suspected).
    Triggers re-encryption of all associated capsules.
    """
    old_key = await get_vault_key(agent_id)
    new_key = generate_key()

    # Re-encrypt all capsules owned by agent
    capsules = await db.get_capsules(owner_id=agent_id)
    for capsule in capsules:
        old_plaintext = aes_gcm_decrypt(capsule.content_encrypted, old_key)
        new_ciphertext = aes_gcm_encrypt(old_plaintext, new_key)
        await db.update_capsule(capsule.id, content_encrypted=new_ciphertext)

    # Store new key (audit logged)
    await db.update_vault_key(agent_id, new_key, version=2)
    await audit_device.log_event(AuditEvent(
        operation="key_rotation",
        resource_id=agent_id,
        result="success",
    ))
```

---

## What Vault Doesn't Do (AI Needs These)

### 1. Semantic Search Over Encrypted Data

**Vault**: No built-in search; requires decryption to inspect content.

**TrustMesh Need**: Search "health monitoring" across 100 encrypted capsules without decrypting all.

**Solution**: SQLite FTS5 + Zig kernel (already implemented in Phase 5)
- Index encrypted capsules at ingest time
- Query tokenized FTS index, return matching capsule IDs
- Decrypt only matching results
- Trust filtering in FTS query (JSON array of accessible IDs)

---

### 2. Trust-Based Sharing (Not Just ACL)

**Vault**: Policies are static, tied to tokens/identities.

**TrustMesh Need**: Trust context changes at query time (agent from different pod, different user group, etc.).

**Solution**: Dynamic trust resolution (already in `trust.py`)
- Query arrives with source_agent_did, source_pod
- System resolves trust level (private→internal→open)
- Policy engine checks capsule against trust level
- Fails fast if trust too low
- Audit logs the decision and why

---

### 3. Agent Identity (DIDs vs Tokens)

**Vault**: Tokens are opaque strings, revocable globally.

**TrustMesh Need**: Agents have persistent identities (DIDs) across pod federation, portable credentials.

**Solution**: DID-based identity (already in design)
- Each agent has a DID (did:key:z... format)
- Agent signs requests with ed25519 private key
- Pod verifies signature + trust context
- DIDs immutable; can rotate keys within DID doc

---

### 4. Temporal Execution (Agent Scheduling)

**Vault**: No built-in task scheduling or cron.

**TrustMesh Need**: Schedule agent tasks (daily health checks, weekly reports, etc.).

**Solution**: PodOS Timeline Kernel (already implemented)
- Timeline entries with cron expressions
- State machine (dormant→pending→active→deactivating→completed)
- Zig kernel ticks every minute, evaluates cron
- On match: emit AGENT_TASK event → Python bridge → agent execution

---

### 5. Cross-Organization Federation

**Vault**: Replication is cluster-to-cluster, not cross-org.

**TrustMesh Need**: Agents from Org A query secrets at Org B with trust boundaries.

**Solution**: Pod federation (already designed)
- Pod A agents get UCAN tokens for Pod B
- Pod B verifies token + source DID against trust network
- Public trust restricts to open capsules only
- Trust levels (private/internal/open) enforce data minimization

---

## HCP Vault Pricing: Cloud Consumption Model

### HCP Vault Secrets (Being Retired June 30, 2026)

**Model**: Per-secret, per-operation charges
- $0.50/secret/month (Standard tier, up to 2,500)
- $0.95/secret/month (Plus tier, up to 25,000)
- Additional charges for API calls beyond included quota

**Problem**: Unpredictable costs for high-volume applications; HCP migrating away.

### HCP Vault Dedicated (Current Model)

**Model**: Per-client + hourly base cost
- Development tier: $0.50/client/hour (minimum 1)
- Essentials tier: $1.20/hour base + $0.10/client/hour
- Standard tier: $3.00/hour base + $0.05/client/hour

**Definition of "Client"**:
- Unique entity initiating requests (person, service, agent)
- Can authenticate via OIDC, LDAP, AppRole, etc.
- Does NOT charge per-secret or per-operation

**Advantage**: Predictable scaling; encourages heavy usage once cluster paid for.

### TrustMesh Cloud Model (If Offered)

**Recommendation**: Hybrid model
```
Base fee: $50/month (1 pod, 50 capsules)

Per-pod scaling:
+ $25/month per additional pod (federation)
+ $0.01/capsule/day (if >50)
+ $0.001/agent/day (if >100 agents total)

Optional features:
+ $10/month: Audit export to S3
+ $15/month: HSM seal wrap (prod security)
+ $20/month: Replication secondary pod (HA)

Throughput: Unlimited API calls (no per-op charge)
           Unlimited agent tasks (no per-task charge)

Discounts:
- 20% for 1-year commitment
- 30% for 3-year commitment
- Non-profit/academic: free tier (1 pod, 10 agents)
```

**Rationale**:
- Base pod cost = fixed infrastructure (SQLite, Zig kernel)
- Capsule/agent cost = storage + compute (incremental)
- Unlimited operations = encourages product engagement
- Per-client pricing (Vault model) doesn't fit agents (agents spawn dynamically)
- Differentiate on **trust network features** (HCP doesn't offer cross-org federation)

---

## Zig Kernel Implementation Roadmap

### Phase 5 (Completed): SQLite FTS5
- `kernel/src/db.zig` - SQLite C API wrapper
- `kernel/src/fts.zig` - FTS5 full-text search
- 6 C exports: `podos_db_open/close`, `podos_fts_upsert/delete/search/reset`
- 14 FTS bridge tests in Python

### Phase 6 (Proposed): Unified Engine Architecture

```zig
// kernel/src/engine.zig
pub const EngineType = enum {
    capsule_store,    // KV engine
    timeline,         // Temporal engine
    transit,          // Encryption engine
    trust,            // Trust resolution engine
};

pub const Engine = struct {
    engine_type: EngineType,
    db: *DB,
    policy_checker: PolicyChecker,

    pub fn init(allocator: Allocator, engine_type: EngineType) !*Engine;
    pub fn read(self: *Engine, resource_id: []const u8, agent_id: []const u8) ![]u8;
    pub fn write(self: *Engine, resource_id: []const u8, data: []const u8) !void;
    pub fn delete(self: *Engine, resource_id: []const u8) !void;
};

// Export unified interface
pub export fn podos_engine_init(engine_type: u32) callconv(.c) ?*opaque {};
pub export fn podos_engine_read(engine: ?*opaque {}, resource_id: [*:0]const u8, agent_id: [*:0]const u8) callconv(.c) i32;
pub export fn podos_engine_write(engine: ?*opaque {}, resource_id: [*:0]const u8, data: [*]const u8, data_len: usize) callconv(.c) i32;
```

### Phase 7 (Proposed): Policy Engine in Zig

```zig
// kernel/src/policy.zig
pub const Policy = struct {
    path: []const u8,
    capabilities: []const []const u8,  // ["read", "execute", ...]
    conditions: ?Condition,  // cron, time window, etc.
};

pub const PolicyChecker = struct {
    policies: std.ArrayList(Policy),

    pub fn can_access(
        self: *PolicyChecker,
        agent_id: []const u8,
        resource_id: []const u8,
        operation: []const u8,  // "read", "write", "execute"
        trust_level: []const u8,  // "private", "internal", "open"
    ) !bool;
};
```

### Phase 8 (Proposed): Audit Device in Zig

```zig
// kernel/src/audit.zig
pub const AuditEvent = struct {
    timestamp: i64,
    agent_id: [*:0]const u8,
    operation: [*:0]const u8,
    resource_id: [*:0]const u8,
    result: [*:0]const u8,  // "allowed", "denied", "error"
    reason: [*:0]const u8,
};

pub export fn podos_audit_log(event: *const AuditEvent) callconv(.c) i32 {
    // Append to immutable WAL
    // Return 0 on success, -1 if write fails
}
```

---

## Summary: Core Patterns to Steal from Vault

| Vault Pattern | TrustMesh Implementation | File/Module |
|---|---|---|
| Seal/Unseal | Three-tier pod initialization | `main.py` lifespan + new `unseal.py` |
| Secrets Engines | Capsule/Timeline/Transit as engines | `routes/` modularization |
| Policies | Trust + UCAN → Policy engine | `trust.py` + new `policy.py` |
| Audit Logging | Immutable agent query log | `audit_log` table + `audit.py` |
| Leases & TTL | UCAN tokens + cascade revocation | `ucan.py` + new `lease.py` |
| Transit Engine | Agent-scoped encryption bridge | `transit.py` endpoint |
| Namespaces | Pod federation + pools | `federation.py` + `models.py` |
| HSM Integration | Pod master key seal wrap | Infrastructure, not code |

---

## Sources

- [Vault Security Model](https://developer.hashicorp.com/vault/docs/internals/security)
- [Vault Seal/Unseal](https://developer.hashicorp.com/vault/docs/concepts/seal)
- [Vault Policies](https://developer.hashicorp.com/vault/docs/concepts/policies)
- [Vault Audit Logging](https://developer.hashicorp.com/vault/docs/audit)
- [Vault Leases](https://developer.hashicorp.com/vault/docs/concepts/lease)
- [HCP Vault Pricing](https://cloud.hashicorp.com/products/vault/pricing)
- [Vault API](https://developer.hashicorp.com/vault/api-docs)
