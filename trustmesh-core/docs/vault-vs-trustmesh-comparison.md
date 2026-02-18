# HashiCorp Vault vs. TrustMesh: Detailed Comparison & Pattern Mapping

## Overview Table: Core Primitives

| Primitive | Vault | TrustMesh Current | TrustMesh with Vault Patterns |
|-----------|-------|-------------------|-------------------------------|
| **Seal/Unseal** | Master key ceremony (Shamir 3-of-5 or HSM) | Pod startup: load vault_keys dict | Three-tier unsealing (metadata → agent authority → execution) |
| **Secrets Storage** | KV v1/v2 engines | Capsule model (encrypted content + metadata) | Capsule store engine (versioning, soft delete, rollback) |
| **Dynamic Secrets** | Temporal credentials (TTL, renewal) | UCAN tokens with exp_time | Lease model (parent-child cascade revocation) |
| **Encryption** | Transit engine (key at rest, ops in place) | Vault keys dict per user | Transit engine (encrypt/decrypt/rotate routes) |
| **Access Control** | Deny-by-default policies (path + capability) | Trust levels (open/internal/private) | Policy engine in Zig (path matching, deny priority) |
| **Audit Logging** | Immutable append-only logs (fail-safe) | Optional, not structured | Mandatory audit device (fail-safe, immutable WAL) |
| **Token Lifecycle** | Periodic tokens with renewal | Tokens with exp_time only | Periodic + renewal (prove liveness) + health monitor |
| **High Availability** | Replication (primary + replica) | Federation (peer discovery) | Pod replication (delta sync, failover) |
| **Multi-Tenancy** | Namespaces (logical isolation) | Per-pod isolation | Pod namespaces (federation-aware) |
| **Policy-as-Code** | Sentinel (advisory/soft/hard mandatory) | Hardcoded trust logic | Temporal policies (cron conditions, rate limits) |
| **HSM Integration** | Auto-unseal via HSM/KMS | Not applicable | HSM seal wrap (master key encrypted by hardware) |

---

## Detailed Feature Comparison

### 1. Seal/Unseal Mechanism

**Vault Model**:
```
Physical Storage (encrypted)
    ↓ [Sealed State]
    ↓
Operator provides 3 of 5 Shamir shares
    ↓
Root key reconstructed in memory
    ↓ [Unsealed State]
    ↓
Barrier decrypted (all data accessible)
```

**Key Insight**: Single binary transition (sealed ↔ unsealed). All data unlocked or none.

**TrustMesh Current**:
```python
# Pod startup
vault_keys[user_id] = derive_key(password, salt)
# (vulnerable to memory inspection, no ceremony)
```

**TrustMesh with Vault Patterns**:
```
Phase 1: Pod Metadata Unsealing
    Admin provides 3 of 5 recovery shares
    Master key reconstructed, stored in TPM/HSM
    Capsule metadata readable
    Agent tasks NOT executable

Phase 2: Agent Authority Unsealing
    Admin approves agent execution
    UCAN ceremony token generated
    Admin signs ceremony token (ed25519)
    Agent vault keys derived and cached
    Agent tasks executable

Phase 3: Per-Task Execution Unsealing (future)
    Agent requests task execution
    System verifies trust context, rate limits
    Ephemeral transit token issued (5-min TTL)
    Task executes with limited-scope token
```

**Why Three Tiers?**
1. **Compliance**: Audit/review opportunity between phases
2. **Security**: Agent authority not automatic; requires admin ceremony
3. **Forensics**: Clear audit trail of who authorized what

**Implementation Cost**: 1-2 days (Shamir + HSM integration optional)

---

### 2. Secrets Engines: Modularity

**Vault Philosophy**: Each secrets engine is independent mount point with:
- Separate authentication paths
- Isolated policies
- Independent key rotation schedule
- Different CRUD operations (KV reads/writes vs. Transit encrypt/decrypt)

**Example Vault Setup**:
```hcl
mount "secret" {
  type = "kv"
  version = 2  # Soft delete, versioning, rollback
}

mount "transit" {
  type = "transit"  # Encryption-as-service
}

mount "aws" {
  type = "aws"
  config = {...}  # Dynamic AWS IAM credentials
}

mount "pki" {
  type = "pki"  # Certificate generation
}

policy "eng-policy" {
  path "secret/eng/*" { capabilities = ["read"] }
  path "transit/encrypt/eng" { capabilities = ["update"] }
}
```

**TrustMesh Current**:
- Single capsule model (KV v2-like)
- No separation between storage, encryption, scheduling
- Monolithic routes file

**TrustMesh with Vault Patterns**:
```python
# routes/capsule.py (KV v2 equivalent)
class CapsuleEngine:
    async def read(capsule_id, agent_id) -> Capsule
    async def list_versions(capsule_id, agent_id) -> List[Version]
    async def rollback(capsule_id, version, agent_id) -> Capsule

# routes/transit.py (Transit equivalent)
class TransitEngine:
    async def encrypt(plaintext, agent_id, mount) -> CipherText
    async def decrypt(ciphertext, agent_id) -> PlainText
    async def rotate(agent_id) -> NewKeyVersion

# routes/timeline.py (Dynamic Secrets equivalent)
class TimelineEngine:
    async def create_entry(agent_id, cron, action) -> Lease
    async def execute_entry(entry_id, agent_id) -> Result
    async def revoke_entry(entry_id) -> None  # Cascade

# routes/trust.py (PKI-like)
class TrustEngine:
    async def issue_cross_pod_token(source_did, target_pod, scopes) -> UCAN
    async def verify_cross_pod_request(token, source_did) -> TrustLevel
```

**Benefits**:
- Clear separation of concerns
- Independent policy per engine
- Easier to add new engines (e.g., Database credentials, SSH keys)
- Vault-like extensibility

**Implementation Cost**: 2 days (refactoring + tests)

---

### 3. Policy Language: Deny-by-Default ACLs

**Vault**:
```hcl
# Policy file (HCL format)
path "secret/*" {
  capabilities = ["read", "list"]
}

path "secret/admin/*" {
  capabilities = ["deny"]  # Explicit deny (highest priority)
}

path "database/creds/prod" {
  capabilities = ["read"]
  required_parameters = ["role"]  # Constrain request params
}
```

**Path Matching Rules**:
1. **Exact**: `secret/foo` matches only `secret/foo`
2. **Glob**: `secret/*` matches `secret/foo`, `secret/bar` (NOT nested)
3. **Segment**: `secret/+/password` matches `secret/x/password` (one path segment)
4. **Priority**: Exact > longer path > glob, `deny` always wins

**Capability Matrix**:
| Operation | HTTP | Capability |
|-----------|------|------------|
| Create | POST/PUT | `create`, `update` |
| Read | GET | `read` |
| Delete | DELETE | `delete` |
| List | LIST | `list` |
| Partial update | PATCH | `patch` |
| Root-level | (special) | `sudo` |
| Deny | (all) | `deny` |

**TrustMesh Current**:
- Hardcoded trust levels (open/internal/private)
- No deny capability (only positive grants)
- No path matching or capability matrix
- Trust resolution logic scattered in gossip.py

**TrustMesh with Vault Patterns**:
```python
# Policy definition (HCL-like)
policy = """
path "capsule/health/*" {
  capabilities = ["read", "list"]
  # Implicit: only "open" trust can read
}

path "capsule/finance/*" {
  capabilities = ["read"]
  # Only "internal" or "private" trust
}

path "capsule/*/admin" {
  capabilities = ["deny"]  # Explicit deny
}

path "timeline/entries/*" {
  capabilities = ["execute"]
  condition = "trust_level >= internal"  # Temporal condition
}
"""

# Compiled to Zig policy checker
class PolicyEngine:
    def __init__(self, policy_hcl):
        self.paths = parse_hcl(policy_hcl)
        self.zig_checker = compile_to_zig(self.paths)

    async def can_access(agent_id, resource_id, operation, trust_level):
        # Fast path matching + capability check in Zig
        return await self.zig_checker.check(...)

# Integration: wrap all routes
@router.get("/api/capsule/{id}")
async def read_capsule(id: str, auth_agent_id: str = Depends(get_current_agent_id)):
    # Resolve trust level (dynamic, at query time)
    trust_level = await resolve_trust(auth_agent_id, local_pod_id)

    # Check policy
    allowed = await policy_engine.can_access(
        auth_agent_id,
        f"capsule/{id}",
        "read",
        trust_level
    )

    if not allowed:
        await audit_device.log("denied")
        raise PermissionError()

    capsule = await db.get_capsule(id)
    await audit_device.log("allowed")
    return capsule
```

**Key Differences from Vault**:
- Vault policies are **static** (declared at server config time)
- TrustMesh policies must be **dynamic** (trust context arrives at query time)
- Solution: Pre-compile HCL to Zig at startup, check at runtime with dynamic trust_level

**Implementation Cost**: 2 days (HCL parser + Zig compiler)

---

### 4. Audit Logging: Tamper-Evident Records

**Vault Model**:
```
┌─────────────────────────────┐
│    Audit Device 1 (file)    │
│ ├─ 2026-02-17 12:34 GET ... │
│ ├─ 2026-02-17 12:35 POST .. │
│ └─ 2026-02-17 12:36 DELETE  │
└─────────────────────────────┘

┌─────────────────────────────┐
│   Audit Device 2 (syslog)   │
│ ├─ 2026-02-17 12:34 GET ... │
│ ├─ 2026-02-17 12:35 POST .. │
│ └─ 2026-02-17 12:36 DELETE  │
└─────────────────────────────┘

Vault Promise: Write to ≥1 device or REFUSE request (fail-safe)
```

**Vault Audit Log Entry** (JSON):
```json
{
  "time": "2026-02-17T12:34:56Z",
  "type": "request",
  "auth": {
    "client_token": "hvs.x...",
    "display_name": "app-1",
    "policies": ["app-policy"]
  },
  "request": {
    "operation": "read",
    "path": "secret/data/db",
    "data": null
  },
  "response": {
    "data": {"username": "admin", "password": "secret"}
  },
  "error": null,
  "request_id": "...",
  "remote_address": "10.0.0.1"
}
```

**TrustMesh Current**:
- Optional agent query logging (inconsistent)
- No fail-safe guarantee
- No tamper-evidence
- Missing context (agent_id, trust_level, reason for deny)

**TrustMesh with Vault Patterns**:
```python
# Mandatory audit device (fail-safe)
class AuditDevice:
    async def log_event(self, event: AuditEvent) -> None:
        """Append to audit log. Fail if I/O error."""
        try:
            await db.insert_audit_log(event)
        except Exception as e:
            # CRITICAL: If audit fails, refuse operation
            # This prevents silent security breaches
            raise AuditFailure(f"Audit write failed: {e}")

# AuditEvent model
@dataclass
class AuditEvent:
    timestamp: float
    agent_id: str
    operation: str  # "read_capsule", "execute_task", "issue_token"
    resource_id: str  # capsule_id, entry_id, agent_id
    trust_level: str  # "open", "internal", "private"
    result: str  # "allowed", "denied", "error"
    reason: str  # WHY allowed/denied (e.g., "trust_level too low")
    request_context: dict  # from_pod, source_did, auth_method
    citadel_risk: str  # "safe", "warning", "blocked"

# Route wrapper (audit before returning)
async def read_capsule_with_audit(capsule_id, agent_id, trust_level):
    try:
        capsule = await db.get_capsule(capsule_id)
        allowed = await policy_engine.can_access(agent_id, capsule_id, "read", trust_level)

        # Log BEFORE returning (fail-safe)
        await audit_device.log_event(AuditEvent(
            timestamp=time.time(),
            agent_id=agent_id,
            operation="read_capsule",
            resource_id=capsule_id,
            trust_level=trust_level,
            result="allowed" if allowed else "denied",
            reason="Policy allows" if allowed else "Trust level insufficient",
            request_context={...},
            citadel_risk="safe",
        ))

        if allowed:
            return capsule
        else:
            raise PermissionError()
    except Exception as e:
        # Log error and re-raise (fail-safe)
        await audit_device.log_event(AuditEvent(
            operation="read_capsule",
            resource_id=capsule_id,
            result="error",
            reason=str(e),
        ))
        raise

# Audit export (compliance)
@router.get("/api/audit/export")
async def export_audit_logs(
    since: float,
    auth_admin_id: str = Depends(require_admin),
):
    logs = await db.query(AuditLog).filter(AuditLog.timestamp >= since).all()

    # HMAC sign for integrity
    data_json = json.dumps([log.to_dict() for log in logs])
    hmac_sig = hmac.new(
        admin_audit_key.encode(),
        data_json.encode(),
        hashlib.sha256
    ).hexdigest()

    return {
        "data": data_json,
        "hmac_sha256": hmac_sig,
        "count": len(logs),
    }
```

**Audit Table Schema** (SQLite):
```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    agent_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    trust_level TEXT NOT NULL,
    result TEXT NOT NULL,
    reason TEXT,
    request_context TEXT,  -- JSON
    citadel_risk TEXT
);

CREATE INDEX idx_audit_agent_ts ON audit_log(agent_id, timestamp);
CREATE INDEX idx_audit_result ON audit_log(result);
```

**Benefits of Vault Pattern**:
1. **Fail-safe**: If audit fails, operation refused (prevents silent security breaches)
2. **Tamper-evident**: HMAC-signed exports, append-only WAL
3. **Compliance**: HIPAA, SOC2, PCI-DSS audit trail requirements met
4. **Forensic**: Rich context (trust_level, reason, risk assessment)

**Implementation Cost**: 1 day (model + routes + audit wrapper)

---

### 5. Leases & Token Lifecycle

**Vault Model**:
```
create_secret() → Lease(id, ttl=30d, renewable=true, parent=null)
                  ↓
                  ├─ Client calls "lease renew" → ttl extended
                  │
                  └─ TTL expires → secret auto-revoked
                     ├─ All children revoked (cascade)
                     └─ Audit logged
```

**Parent-Child Relationships**:
```
Agent Lease (24h, renewable=true, parent=null)
    ├─ Task 1 Lease (5min, renewable=false, parent=AgentLease)
    │   ├─ Capsule Read Token (1min, parent=Task1Lease)
    │   └─ Capsule Write Token (1min, parent=Task1Lease)
    │       [On Task1 expiry: all children revoked]
    └─ Task 2 Lease (5min, renewable=false, parent=AgentLease)
        [On AgentLease expiry: Task1+Task2 all revoked]
```

**TrustMesh Current**:
- UCAN tokens with exp_time
- No parent-child relationships
- No renewal mechanism
- No cascade revocation

**TrustMesh with Vault Patterns**:
```python
# Modified UCAN token model
class UCANToken(Base):
    __tablename__ = "ucan_tokens"
    id: str
    issuer: str
    subject: str
    payload: str
    signature: str
    created_at: float
    exp_time: float  # Existing
    parent_token_id: str  # NEW
    revoked_at: float  # NEW
    renewable: bool  # NEW
    last_renewed_at: float  # NEW
    renewal_count: int  # NEW

    children = relationship("UCANToken", backref="parent", foreign_keys=[parent_token_id])

# Cascade revocation (Vault-style)
async def revoke_token_cascade(token_id: str) -> int:
    token = await db.get_ucan_token(token_id)
    revoked_count = 1
    token.revoked_at = time.time()
    await db.update_ucan_token(token)

    # Cascade to children
    for child in token.children:
        revoked_count += await revoke_token_cascade(child.id)

    # Audit
    await audit_device.log_event(AuditEvent(
        operation="revoke_token_cascade",
        resource_id=token_id,
        result="success",
        reason=f"cascaded {revoked_count} tokens"
    ))

    # Timeline event (pause agent if agent token)
    if token.subject.startswith("agent:"):
        await timeline_engine.emit_event(
            AgentPaused(agent_id=token.subject, reason="parent_revoked")
        )

    return revoked_count

# Token renewal (Vault-style)
@router.post("/api/auth/renew")
async def renew_token(
    token_id: str,
    auth_token: str = Depends(get_current_token),
):
    token = await db.get_ucan_token(token_id)
    if not token.renewable:
        raise ValueError("Token not renewable")

    renewal_ttl = 86400  # 24h
    token.exp_time = time.time() + renewal_ttl
    token.last_renewed_at = time.time()
    token.renewal_count += 1
    await db.update_ucan_token(token)

    await audit_device.log_event(AuditEvent(
        operation="token_renew",
        resource_id=token_id,
        result="success",
        reason=f"renewal #{token.renewal_count}",
    ))

    return {"token_id": token_id, "exp_time": token.exp_time}

# Background health monitor (Vault-style)
async def monitor_token_health():
    while True:
        await asyncio.sleep(3600)  # 1 hour

        stale_tokens = await db.query(UCANToken).filter(
            UCANToken.renewable == True,
            UCANToken.last_renewed_at < time.time() - 86400,
        ).all()

        for token in stale_tokens:
            agent_id = token.subject
            await revoke_token_cascade(token.id)

            await audit_device.log_event(AuditEvent(
                operation="agent_auto_pause",
                resource_id=agent_id,
                result="success",
                reason="token not renewed for 24h",
            ))

            # Notify admin
            await notify_admin(f"Agent {agent_id} auto-paused (inactive)")
```

**Benefits**:
1. **Security**: Parent token compromise doesn't affect unrelated children
2. **Lifecycle**: Cascade prevents orphaned tokens (cleanup on parent expiry)
3. **Observability**: Renewal count shows token usage pattern
4. **Health**: Auto-pause inactive agents (no heartbeat for 24h)

**Implementation Cost**: 1 day (model + cascade logic + health monitor)

---

### 6. Transit Engine: Encryption-as-a-Service

**Vault Transit**:
```
Application:
    ├─ POST /transit/encrypt → Vault
    │       plaintext + policy
    │       ← ciphertext + key_version
    │
    └─ POST /transit/decrypt → Vault
            ciphertext
            ← plaintext

Key Rotation:
    Admin: POST /transit/rotate/my-app
           ← new key version (doesn't re-encrypt existing ciphertexts)
           (Next decrypt uses new key automatically)

Transit Advantages:
    1. App never holds keys (reduces blast radius)
    2. Keys rotate without app downtime
    3. Key version embedded in ciphertext (auto-upgrade on decrypt)
```

**TrustMesh Current**:
- Vault keys dict (in-memory, vulnerable)
- Capsule content encrypted at model save time
- No key versioning

**TrustMesh with Vault Patterns**:
```python
# Transit routes (Vault-like)
@router.post("/api/transit/encrypt")
async def transit_encrypt(
    plaintext: str,
    agent_id: str,
    mount: str = "capsule",
    auth_agent_id: str = Depends(get_current_agent_id),
):
    """Encrypt plaintext under agent_id's vault key."""
    vault_key = await get_vault_key(agent_id)
    key_version = await get_key_version(agent_id)
    ciphertext = aes_gcm_encrypt(plaintext, vault_key)

    # Embed version: v{key_version}.{ciphertext}
    result = f"v{key_version}.{ciphertext}"

    return {"ciphertext": result, "key_version": key_version}

@router.post("/api/transit/decrypt")
async def transit_decrypt(
    ciphertext: str,
    auth_agent_id: str = Depends(get_current_agent_id),
):
    """Decrypt ciphertext under agent_id's vault key."""
    # Parse: v{version}.{ciphertext}
    parts = ciphertext.split(".", 1)
    key_version = int(parts[0][1:])
    vault_key = await get_vault_key_version(auth_agent_id, key_version)
    plaintext = aes_gcm_decrypt(parts[1], vault_key)

    return {"plaintext": plaintext}

@router.post("/api/transit/rotate")
async def transit_rotate(
    agent_id: str,
    auth_admin_id: str = Depends(require_admin),
):
    """Rotate agent's vault key (e.g., after compromise detected)."""
    old_key = await get_vault_key(agent_id)
    new_key = generate_key()
    old_version = await get_key_version(agent_id)
    new_version = old_version + 1

    # Re-encrypt all capsules owned by agent
    capsules = await db.get_capsules(owner_id=agent_id)
    for capsule in capsules:
        plaintext = aes_gcm_decrypt(capsule.content_encrypted, old_key)
        new_ciphertext = aes_gcm_encrypt(plaintext, new_key)
        await db.update_capsule(capsule.id, content_encrypted=new_ciphertext)

    # Store new key version
    await db.update_vault_key(agent_id, new_key, version=new_version)

    await audit_device.log_event(AuditEvent(
        operation="key_rotation",
        resource_id=agent_id,
        result="success",
        reason=f"v{old_version} → v{new_version}",
    ))

    return {"new_version": new_version}

# Key versioning table
class VaultKeyVersion(Base):
    __tablename__ = "vault_key_versions"
    id = Column(Integer, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    version = Column(Integer, nullable=False)
    key_encrypted = Column(String, nullable=False)  # Encrypted with master_key
    created_at = Column(Float, nullable=False)
    rotated_at = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_id", "version"),
    )
```

**Cross-Pod Transit** (federation):
```python
# Pod A issues scoped transit token to agent
@router.post("/api/trust/issue-transit-token")
async def issue_cross_pod_token(
    target_pod_id: str,
    agent_id: str,
    scopes: List[str],  # ["capsule/health/*", "timeline/*"]
    ttl_seconds: int = 300,
    auth_admin_id: str = Depends(require_admin),
):
    """
    Issue a cross-pod transit token.
    Agent from Pod A can use this to query Pod B with limited scope.
    """
    target_pod = await get_pod(target_pod_id)

    # Create UCAN token (agent can decrypt Pod B capsules with this)
    token = create_ucan_token(
        issuer=local_pod_id,
        subject=agent_id,
        scopes=scopes,
        exp_time=time.time() + ttl_seconds,
        parent_pod=target_pod_id,
    )

    # Encrypt with Pod B's public key (only Pod B can decrypt)
    encrypted_token = rsa_encrypt(
        token.to_json(),
        target_pod.public_key,
    )

    return {
        "encrypted_token": encrypted_token,
        "ttl_seconds": ttl_seconds,
        "target_pod": target_pod_id,
    }

# Pod B verifies and decrypts transit token
@router.post("/api/trust/verify-transit-token")
async def verify_transit_token(
    encrypted_token: str,
):
    """Pod B receives encrypted token from Pod A's agent."""
    # Decrypt with local private key
    token_json = rsa_decrypt(encrypted_token, local_private_key)
    token = UCANToken.from_json(token_json)

    # Verify signature, expiry, scopes
    verify_ucan_signature(token)
    if token.exp_time < time.time():
        raise ValueError("Token expired")

    return {
        "agent_id": token.subject,
        "scopes": token.scopes,
        "valid": True,
    }
```

**Benefits**:
1. **Separation**: Key management decoupled from application
2. **Rotation**: Rotate key without re-encrypting (version in ciphertext)
3. **Audit**: All encryption/decryption logged
4. **Multi-agent**: Each agent has its own key (one compromise doesn't affect others)

**Implementation Cost**: 1.5 days (routes + key versioning + cross-pod token)

---

## Threat Model: What TrustMesh Adds

### In-Scope (Defended)

**Vault In-Scope** (that TrustMesh inherits):
- Eavesdropping (TLS)
- Data tampering (AES-GCM authentication)
- Unauthorized access (ACLs)
- Lack of accountability (audit logs)
- Secret confidentiality (encryption)
- Availability (replication)

**TrustMesh Additions**:
1. **Agent Compromise**: If agent is compromised, it can query capsules within its trust level
   - Defense: Rate limiting per agent, statistical anomaly detection, sandbox execution
   - Audit: All agent queries logged with trust decision and reason

2. **Cross-Pod DID Spoofing**: Attacker pretends to be agent from Pod A while on Pod B
   - Defense: Agent card verification (fetch from `.well-known/agent-card.json`)
   - Defense: ed25519 signature verification on all cross-pod requests

3. **Trust Context Leakage**: Public trust queries inadvertently reveal organizational structure
   - Defense: Citadel output scanning (soft-leak patterns)
   - Defense: Data minimization (public trust gets only metadata, no names)

### Out-of-Scope (Not Defended)

**Vault Out-of-Scope** (that TrustMesh accepts):
- Storage backend compromise (if attacker controls SQLite file)
- Secret existence disclosure (encrypted data reveals that secrets exist)
- Memory analysis (attacker inspects running Zig kernel or Python process)
- Host code execution (OS-level compromise)
- Malicious admin configuration
- Compromised client credentials (token theft)
- External system vulnerabilities

**TrustMesh Additions to Out-of-Scope**:
- Pod hardware compromise (USB theft, cold boot attacks)
- Zig kernel memory inspection (if attacker can dump process)
- SQLite WAL tampering (if attacker has file system write access)
- Agent model extraction (running inference on agent outputs to reverse-engineer logic)
- Cross-pod DID creation (attacker creates DID, asks Pod B for access—defended by Pod B's trust rules, not TrustMesh)

---

## Cloud Pricing Comparison

### HCP Vault Secrets (Retiring June 2026)

**Model**: Per-secret, per-operation
- Standard: $0.50/secret/month (up to 2,500)
- Plus: $0.95/secret/month (up to 25,000)
- Extra: $0.01 per API call above quota

**Problem**: Unpredictable costs for high-volume use. HCP deprecating this model.

### HCP Vault Dedicated (Current)

**Model**: Per-client + hourly base
- Development: $0.50/client/hour (min 1 client)
- Essentials: $1.20/hour base + $0.10/client/hour
- Standard: $3.00/hour base + $0.05/client/hour

**"Client"**: Unique entity initiating requests (person, service, bot, agent)

**Example Costs** (monthly, ~730 hours):
```
Standard tier (100 clients):
  Base: $3/hour × 730h = $2,190
  Clients: $0.05/client/h × 100 × 730h = $3,650
  Total: ~$5,840/month
```

**Advantage**: Predictable scaling. Heavy usage encouraged once cluster paid for.

### TrustMesh Proposed Model (If Offered)

**Base Tier**:
```
Base fee: $50/month (1 pod, up to 50 capsules, 10 agents)

Scaling:
+ $25/month per additional pod (federation)
+ $0.01/capsule/day (if >50 capsules total)
+ $0.001/agent/day (if >100 agents total)

Optional Features:
+ $10/month: Audit export to S3 (HIPAA compliance)
+ $15/month: HSM seal wrap (FIPS 140-2)
+ $20/month: Replication secondary pod (HA)
+ $30/month: Priority support

Discounts:
- 20% for 1-year upfront
- 30% for 3-year upfront
- Non-profit/academic: free tier (1 pod, 10 agents, 1 month retention)

Throughput Guarantee:
- Unlimited API calls (no per-operation charge)
- Unlimited agent tasks (no per-task charge)
- Unlimited capsule versions (no per-version charge)
```

**Rationale**:
1. **Base pod** (SQLite + Zig kernel) has fixed infrastructure cost
2. **Storage** (capsules, agents) has incremental cost
3. **Operations** (API calls, tasks) are free (amortized in base)
4. **Differentiation**: Vault doesn't offer cross-org federation + trust networks
5. **Per-agent not per-client**: Vault model doesn't fit because agents spawn dynamically

**Example Costs** (monthly):
```
Small pod (1 pod, 50 capsules, 20 agents, no extra features):
  Base: $50
  Total: $50/month

Medium pod (2 pods, 200 capsules, 150 agents):
  Base: $50
  Pod 2: +$25
  Capsules (150 extra): +150 × $0.01 = +$4.50
  Agents (50 extra): +50 × $0.001 = +$0.05
  Total: ~$79.50/month

Large deployment (5 pods, 1000 capsules, 500 agents, S3 + HSM + HA):
  Base: $50
  Pods: +4 × $25 = +$100
  Capsules: +950 × $0.01 = +$9.50
  Agents: +400 × $0.001 = +$0.40
  S3 export: +$10
  HSM: +$15
  Replication: +$20
  Total: ~$204.90/month

(Compare to Vault: 100 clients on Standard would be ~$5,840/month)
```

**TrustMesh Advantage**: No per-operation charges (agents can run amok without cost spike). Encourages engagement.

---

## Summary: What to Steal from Vault

### Must-Have (Security + Compliance)

1. **Mandatory Audit Logging**
   - Fail-safe guarantee (if audit fails, refuse operation)
   - Tamper-evident (HMAC-signed exports)
   - Rich context (agent_id, trust_level, reason)
   - Estimated effort: **1 day**

2. **Cascading Token Revocation**
   - Parent-child relationships in UCAN tokens
   - Cascade on parent expiry or admin revoke
   - Enables "Agent pause" (revoke agent → pause all tasks)
   - Estimated effort: **1 day**

3. **Explicit Deny Capability**
   - `deny` always wins over other policies
   - Prevents accidental over-permission
   - Standard Vault pattern
   - Estimated effort: **0.5 day** (in policy engine)

### Should-Have (Enterprise Features)

4. **Three-Tier Pod Unsealing**
   - Metadata unsealing (capsules readable)
   - Agent authority unsealing (tasks executable)
   - Execution unsealing per-task (ephemeral tokens)
   - Enables compliance gateway
   - Estimated effort: **2 days**

5. **Transit Engine (Encryption-as-a-Service)**
   - Encrypt/decrypt/rotate routes
   - Key versioning in ciphertext
   - Per-agent key management
   - Cross-pod transit tokens
   - Estimated effort: **1.5 days**

6. **Policy Engine in Zig**
   - HCL-like policy language
   - Path matching (exact, glob, segment)
   - Deny-by-default ACLs
   - Temporal conditions (cron, time windows)
   - Estimated effort: **2 days**

### Nice-to-Have (Operations)

7. **Token Renewal + Health Monitor**
   - Periodic tokens with renewal requirement
   - Background health check (auto-pause inactive agents)
   - Heartbeat proof-of-liveness
   - Estimated effort: **1 day**

8. **Audit Export (Compliance)**
   - HMAC-signed JSON/CSV export
   - External syslog integration
   - S3 sync for long-term storage
   - Estimated effort: **1 day**

9. **Pod Replication (HA/DR)**
   - Primary + replica setup
   - Delta sync (capsule changes since version N)
   - Failover mechanism
   - Estimated effort: **2.5 days** (Phase 2)

---

## Quick Decision Matrix

**Use Vault Pattern If**:
- Compliance/security requirement (audit, deny, fail-safe)
- Proven at scale (100M+ users rely on it)
- Simplifies TrustMesh design (compartmentalization)
- Documented in Vault's own docs

**Don't Use If**:
- TrustMesh has different threat model (e.g., agent compromise is in-scope for Vault)
- Adds complexity without benefit (e.g., HSM integration for non-sensitive data)
- Conflicts with agent-native design (e.g., per-operation charges for agents)

---

## Sources

- [Vault Architecture](https://developer.hashicorp.com/vault/docs)
- [Vault Security Model](https://developer.hashicorp.com/vault/docs/internals/security)
- [Vault Audit Logging](https://developer.hashicorp.com/vault/docs/audit)
- [Vault Leases](https://developer.hashicorp.com/vault/docs/concepts/lease)
- [Vault Policies](https://developer.hashicorp.com/vault/docs/concepts/policies)
- [HCP Vault Pricing](https://cloud.hashicorp.com/products/vault/pricing)
- Project documentation: `CLAUDE.md`, `MEMORY.md`
