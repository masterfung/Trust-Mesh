# Vault Architecture → TrustMesh Implementation Priorities

## Quick Reference: What to Implement First

This document prioritizes Vault patterns for TrustMesh, ordered by impact and feasibility.

---

## Priority 1: Mandatory Audit Logging (Security + Compliance)

**Why Now?**
- Federation requires accountability (cross-pod queries need audit trail)
- HIPAA/SOC2 compliance depends on tamper-evident logs
- Currently optional; make mandatory for all agent operations
- Low implementation cost; high assurance value

**Scope**:
- Audit table schema (agent_id, operation, resource_id, trust_level, result, timestamp)
- Fail-safe: if audit write fails, refuse the operation
- SQLite WAL provides durability; index on (agent_id, timestamp) for queries

**Implementation**:
```python
# File: trustmesh-core/src/audit.py (NEW)
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

class AuditOperation(str, Enum):
    READ_CAPSULE = "read_capsule"
    WRITE_CAPSULE = "write_capsule"
    EXECUTE_TASK = "execute_task"
    ISSUE_TOKEN = "issue_token"
    QUERY_CROSS_POD = "query_cross_pod"
    REVOKE_AGENT = "revoke_agent"

@dataclass
class AuditEvent:
    timestamp: float
    agent_id: str
    operation: AuditOperation
    resource_id: str  # capsule_id, entry_id, agent_id
    trust_level: str  # "open", "internal", "private"
    result: str  # "allowed", "denied", "error"
    reason: str
    request_context: dict  # from_pod, auth_method, etc.
    citadel_risk: str  # "safe", "warning", "blocked"

class AuditDevice:
    async def log_event(self, event: AuditEvent) -> None:
        """Fail-safe: raise if write fails"""
        pass

# In models.py (NEW)
class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    timestamp = Column(Float, nullable=False, index=True)
    agent_id = Column(String, nullable=False, index=True)
    operation = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    trust_level = Column(String, nullable=False)
    result = Column(String, nullable=False)
    reason = Column(String)
    request_context = Column(String)  # JSON
    citadel_risk = Column(String)

    __table_args__ = (
        Index("idx_audit_agent_ts", "agent_id", "timestamp"),
    )
```

**Integration Points**:
- Wrap all capsule reads: `read_capsule()` → `audit_log()`
- Wrap all agent tasks: `execute_entry()` → `audit_log()`
- Wrap cross-pod queries: `query_cross_pod()` → `audit_log()`
- Middleware: Pre-response, fail if audit fails (abort transaction)

**Deliverable**:
- `audit.py` module + `AuditLog` model
- Decorator: `@audit_required` (wraps routes, logs before response)
- 15+ test cases (allowed, denied, error scenarios)
- Estimated effort: **4-6 hours**

---

## Priority 2: Cascading Lease/Token Revocation

**Why Now?**
- Agent compromise requires fast cleanup (revoke agent token → cascade to all its task tokens)
- Currently no parent-child relationship in UCAN tokens
- Vault pattern is proven (Vault uses this extensively)
- Enables "Agent pause" feature (admin revokes agent → all tasks pause)

**Scope**:
- Add `parent_token_id` to UCAN token model
- Implement `revoke_cascade()` function
- Timeline integration: emit event on cascade (triggers agent state machine reset)

**Implementation**:
```python
# In models.py (MODIFY)
class UCANToken(Base):
    __tablename__ = "ucan_tokens"
    id = Column(String, primary_key=True)
    issuer = Column(String, nullable=False)  # pod_id
    subject = Column(String, nullable=False)  # agent_did
    payload = Column(String, nullable=False)  # JSON
    signature = Column(String, nullable=False)
    created_at = Column(Float, nullable=False)
    exp_time = Column(Float, nullable=False, index=True)
    parent_token_id = Column(String, ForeignKey("ucan_tokens.id"), nullable=True)  # NEW
    revoked_at = Column(Float, nullable=True)  # NEW

    children = relationship(
        "UCANToken",
        backref=backref("parent", remote_side=[id]),
        foreign_keys=[parent_token_id],
    )

# In ucan.py (NEW FUNCTION)
async def revoke_token_cascade(token_id: str) -> int:
    """
    Revoke token and all its children recursively.
    Returns count of revoked tokens.
    Audit logs the cascade.
    Emits timeline event for agent state machine.
    """
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

    # Timeline event (if agent token)
    if token.subject.startswith("agent:"):
        await timeline_engine.emit_event(
            AgentPaused(agent_id=token.subject, reason="token_cascade_revoke")
        )

    return revoked_count
```

**Integration Points**:
- Agent routes: `DELETE /api/agents/{agent_id}` → cascade revoke all agent tokens
- Timeline: `DELETE /api/timeline/entries/{entry_id}` → cascade revoke task tokens
- Cross-pod: Ghost user removal → cascade revoke federation tokens

**Deliverable**:
- Updated UCAN token model (parent_token_id, revoked_at)
- `revoke_token_cascade()` function
- Audit logging on cascade
- Timeline integration (AgentPaused event)
- 10+ test cases (single, cascade depth=3, cross-pod)
- Estimated effort: **3-4 hours**

---

## Priority 3: Three-Tier Pod Initialization Ceremony

**Why Now?**
- Federation requires formal unsealing (can't trust pod unlocked at startup)
- Separates "pod can read metadata" from "agents can execute tasks"
- Enables audit/review before agents activate (compliance requirement)
- Aligns with Vault's gradual unsealing philosophy

**Scope**:
- Add pod state machine (sealed → metadata_unsealed → agent_authority_unsealed → fully_operational)
- Recovery shares (Shamir 3-of-5) for master key reconstruction
- UCAN ceremony for agent authority (admin must approve)
- Zig kernel exports: `podos_unseal_step(phase, secret)` → `i32`

**Implementation**:
```python
# In models.py (NEW)
class PodState(str, Enum):
    SEALED = "sealed"
    METADATA_UNSEALED = "metadata_unsealed"
    AGENT_AUTHORITY_UNSEALED = "agent_authority_unsealed"
    FULLY_OPERATIONAL = "fully_operational"

class Pod(Base):
    __tablename__ = "pods"
    id = Column(String, primary_key=True)
    state = Column(String, default=PodState.SEALED)  # NEW
    master_key_encrypted = Column(String, nullable=False)  # HSM-wrapped
    recovery_shares_needed = Column(Integer, default=3)
    recovery_shares_provided = Column(Integer, default=0)
    agent_authority_unlocked_at = Column(Float, nullable=True)

# In main.py (LIFESPAN)
@app.on_event("startup")
async def startup():
    pod = await get_local_pod()

    # Phase 1: Operator unseals metadata
    print("Pod sealed. Waiting for recovery shares...")
    shares = []
    for i in range(3):
        share = input(f"Recovery share {i+1}/3: ")
        shares.append(share)

    master_key = shamir_reconstruct(shares)
    store_in_hsm_or_memory(master_key)  # TPM if available
    pod.state = PodState.METADATA_UNSEALED
    await db.update_pod(pod)
    print("Pod metadata unsealed. Capsules readable.")

    # Phase 2: Delayed - operator authorizes agents
    print("Awaiting agent authority ceremony...")
    # (Could be manual approval in UI, or time-delayed)

# In unseal.py (NEW)
async def request_agent_authority(pod_id: str, admin_token: str) -> str:
    """
    Admin requests to unseal agent authority.
    System generates a ceremony token (one-time, expires in 1h).
    Admin must sign ceremony token to complete.
    """
    pod = await get_pod(pod_id)
    if pod.state != PodState.METADATA_UNSEALED:
        raise ValueError("Pod not in metadata-unsealed state")

    ceremony_token = generate_ceremony_token(pod_id, expires_in=3600)
    return ceremony_token

async def complete_agent_authority(
    pod_id: str,
    ceremony_token: str,
    admin_signature: str  # ed25519 signature of ceremony_token
) -> str:
    """
    Complete agent authority ceremony.
    Derives all agent vault keys.
    Returns UCAN token for agent initialization.
    """
    pod = await get_pod(pod_id)
    verify_ceremony_token(ceremony_token)
    verify_admin_signature(ceremony_token, admin_signature, pod.admin_did)

    # Generate agent vault keys
    master_key = retrieve_from_hsm(pod_id)
    for agent in await db.get_agents_for_pod(pod_id):
        vault_key = derive_key(master_key, agent.did)
        vault_keys[agent.did] = vault_key

    pod.state = PodState.AGENT_AUTHORITY_UNSEALED
    pod.agent_authority_unlocked_at = time.time()
    await db.update_pod(pod)

    # Audit
    await audit_device.log_event(AuditEvent(
        operation="unseal_agent_authority",
        resource_id=pod_id,
        result="success"
    ))

    return generate_pod_operation_token(pod_id)  # For agents to initialize
```

**Zig Kernel**:
```zig
// kernel/src/unseal.zig (NEW)
pub const PodSealState = enum(u32) {
    sealed = 0,
    metadata_unsealed = 1,
    agent_authority_unsealed = 2,
    fully_operational = 3,
};

pub export fn podos_unseal_step(
    phase: u32,  // PodSealState
    secret: [*:0]const u8,
) callconv(.c) i32 {
    switch (phase) {
        0 => {
            // Phase 1: Reconstruct master key from Shamir shares
            // Validate share checksum
            // Store in memory or HSM
            return 0;
        },
        1 => {
            // Phase 2: Verify admin ceremony signature
            // Derive agent keys
            return 0;
        },
        else => return -1,
    }
}

pub export fn podos_get_pod_state() callconv(.c) u32 {
    // Return current PodSealState
}
```

**Integration Points**:
- Main.py startup: pause until Phase 1 complete
- API guard: `@require_pod_state(METADATA_UNSEALED)` on capsule routes
- API guard: `@require_pod_state(AGENT_AUTHORITY_UNSEALED)` on task routes
- UI: Unseal ceremony wizard (multi-step form)

**Deliverable**:
- PodState enum + Pod.state model column
- `unseal.py` module (request/complete ceremony)
- Zig kernel `podos_unseal_step()` + `podos_get_pod_state()`
- Route decorators: `@require_pod_state()`
- 12+ test cases (full ceremony, phase skip, invalid share, signature mismatch)
- Estimated effort: **6-8 hours**

---

## Priority 4: Policy Engine (Zig Kernel)

**Why Now?**
- Vault policies are proven ACL model (deny-by-default, path matching, capability checks)
- Currently trust resolution in Python (gossip.py); move to Zig for speed
- Enables future: dynamic policies (enforce time windows, rate limits)
- Foundation for Phase 6 (unified engine architecture)

**Scope**:
- HCL-like policy syntax (or JSON) for admin to define
- Zig policy checker: can_access(agent_id, resource_id, operation, trust_level) → bool
- C ABI export: `podos_policy_check()`
- Python bridge: compile policies to Zig, call for every operation

**Implementation**:
```zig
// kernel/src/policy.zig (NEW)
pub const Capability = enum(u8) {
    read = 0,
    write = 1,
    execute = 2,
    delete = 3,
    admin = 4,
};

pub const PathPattern = struct {
    path: []const u8,  // "capsule/health/*" or "timeline/entries/+"
    capabilities: []const Capability,
    required_params: ?[]const []const u8,  // e.g., ["agent_id"]
    // Future: conditions (cron, time window, rate limit)
};

pub const PolicySet = struct {
    policies: std.ArrayList(PathPattern),
    default_deny: bool,
};

pub fn path_match(pattern: []const u8, request_path: []const u8) bool {
    // Exact: "secret/foo" == "secret/foo"
    // Glob: "secret/*" matches "secret/foo", "secret/bar"
    // Segment: "secret/+/password" matches "secret/x/password"
    // NOT regex; simple glob only (as Vault does)
}

pub export fn podos_policy_check(
    policy_set: ?*const opaque {},
    agent_id: [*:0]const u8,
    resource_id: [*:0]const u8,
    operation: u8,  // Capability enum
    trust_level: [*:0]const u8,  // "open", "internal", "private"
) callconv(.c) i32 {
    // Return 1 if allowed, 0 if denied, -1 if error
}
```

**Python Bridge**:
```python
# In policy.py (NEW)
from ctypes import c_void_p, c_char_p, c_ubyte

# Policy definition (admin creates)
"""
path "capsule/health/*" {
    capabilities = ["read"]
    # Only if trust_level >= "internal"
}

path "timeline/entries/daily_checkin" {
    capabilities = ["execute"]
    condition = "cron == '0 9 * * *'"
}

path "*/admin/*" {
    capabilities = ["deny"]
}
"""

class PolicyEngine:
    def __init__(self, policy_hcl: str):
        self.policy_set = parse_hcl(policy_hcl)
        self.zig_policy_set = compile_to_zig(self.policy_set)

    async def can_access(
        self,
        agent_id: str,
        resource_id: str,
        operation: str,  # "read", "write", "execute", "delete"
        trust_level: str,  # "open", "internal", "private"
    ) -> bool:
        op_code = {"read": 0, "write": 1, "execute": 2, "delete": 3, "admin": 4}[operation]
        result = libpodos.podos_policy_check(
            self.zig_policy_set,
            agent_id.encode(),
            resource_id.encode(),
            op_code,
            trust_level.encode(),
        )
        return result == 1
```

**Integration Points**:
- Capsule routes: wrap with `policy_engine.can_access(agent_id, capsule_id, "read", trust_level)`
- Timeline routes: wrap with `policy_engine.can_access(agent_id, entry_id, "execute", trust_level)`
- Gossip queries: filter results through policy checks

**Deliverable**:
- `kernel/src/policy.zig` (PathPattern, PolicySet, podos_policy_check)
- `src/policy.py` (HCL parser, bridge, PolicyEngine class)
- 20+ Zig tests (exact, glob, segment, deny priority)
- 15+ Python integration tests (capsule/timeline access)
- Estimated effort: **8-10 hours**

---

## Priority 5: Transit Engine (Encryption-as-a-Service)

**Why Now?**
- Vault pattern for per-agent key management
- Enables agent-specific encryption (rotate agent key without re-encrypting all capsules)
- Foundation for cross-pod encryption (Pod A agent → Pod B sealed token)
- Separates "data at rest" (pod-wide key) from "data in flight" (agent-specific)

**Scope**:
- Transit routes: `POST /api/transit/encrypt`, `/api/transit/decrypt`, `/api/transit/rotate`
- Key versioning in ciphertext (agent can rotate key, old ciphertexts still decrypt)
- Audit log all encrypt/decrypt operations
- Cross-pod: transit token (scoped key, time-limited)

**Implementation**:
```python
# In routes/transit.py (NEW)
from fastapi import APIRouter, Depends
from src.auth import get_current_agent_id
from src.audit import audit_device
from src.crypto import aes_gcm_encrypt, aes_gcm_decrypt

router = APIRouter(prefix="/api/transit", tags=["transit"])

@router.post("/encrypt")
async def transit_encrypt(
    plaintext: str,
    agent_id: str,
    mount: str = "capsule",  # mount path for scoping
    auth_agent_id: str = Depends(get_current_agent_id),
):
    """
    Encrypt plaintext under agent_id's vault key.
    Returns ciphertext with versioned key ID.
    """
    if agent_id != auth_agent_id and not is_admin(auth_agent_id):
        raise PermissionError("Can only encrypt for own agent")

    vault_key = await get_vault_key(agent_id)
    key_version = 1  # TODO: track versions
    ciphertext = aes_gcm_encrypt(plaintext, vault_key)

    # Embed version: v{key_version}.{ciphertext}
    result = f"v{key_version}.{ciphertext}"

    await audit_device.log_event(AuditEvent(
        operation="transit_encrypt",
        resource_id=agent_id,
        result="success",
    ))

    return {"ciphertext": result, "key_version": key_version}

@router.post("/decrypt")
async def transit_decrypt(
    ciphertext: str,
    auth_agent_id: str = Depends(get_current_agent_id),
):
    """
    Decrypt ciphertext under agent_id's vault key.
    Parses version from ciphertext prefix.
    """
    # Parse: v{version}.{ciphertext}
    parts = ciphertext.split(".", 1)
    if len(parts) != 2 or not parts[0].startswith("v"):
        raise ValueError("Invalid ciphertext format")

    key_version = int(parts[0][1:])
    vault_key = await get_vault_key_version(auth_agent_id, key_version)
    plaintext = aes_gcm_decrypt(parts[1], vault_key)

    await audit_device.log_event(AuditEvent(
        operation="transit_decrypt",
        resource_id=auth_agent_id,
        result="success",
    ))

    return {"plaintext": plaintext}

@router.post("/rotate")
async def transit_rotate(
    agent_id: str,
    auth_admin_id: str = Depends(require_admin),
):
    """
    Rotate agent's vault key (e.g., after compromise suspected).
    Re-encrypts all associated capsules.
    Audit logs the rotation.
    """
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
        reason=f"rotated from v{old_version} to v{new_version}",
    ))

    return {"agent_id": agent_id, "new_version": new_version}
```

**Integration Points**:
- Agent initialization: derive vault_key via transit engine
- Cross-pod queries: Pod A issues transit token to agent, agent can only decrypt via Pod B transit service
- Capsule encryption: use transit engine for encrypt/decrypt (instead of in-memory keys)

**Deliverable**:
- `src/routes/transit.py` (encrypt, decrypt, rotate routes)
- Key versioning in ciphertext format
- Audit logging on all operations
- Cross-pod transit token generation
- 10+ test cases (single key, rotation, version mismatch)
- Estimated effort: **4-5 hours**

---

## Priority 6: Leases & Periodic Token Renewal

**Why Now?**
- Agent health check (token renewal proves agent still alive)
- Vault pattern: periodic tokens require active renewal (security signal)
- Enables "Agent dead detection" (if token not renewed for 24h, auto-pause)
- Foundation for agent monitoring dashboard

**Scope**:
- Token renewal endpoint: `POST /api/auth/renew`
- Periodic token model: `renewable=true`, `last_renewed_at`
- Background job: check token expiry, pause agent if not renewed
- Audit log all renewals

**Implementation**:
```python
# In models.py (MODIFY)
class UCANToken(Base):
    __tablename__ = "ucan_tokens"
    # ... existing fields ...
    renewable = Column(Boolean, default=False)
    last_renewed_at = Column(Float, nullable=True)
    renewal_count = Column(Integer, default=0)

# In routes/auth.py
@router.post("/renew")
async def renew_token(
    token_id: str,
    auth_token: str = Depends(get_current_token),
):
    """
    Renew a periodic token.
    Extends exp_time by renewal_ttl.
    """
    token = await db.get_ucan_token(token_id)
    if not token.renewable:
        raise ValueError("Token not renewable")

    if token.exp_time < time.time():
        raise ValueError("Token already expired")

    # Extend
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

# Background job (in lifespan)
async def monitor_token_health():
    """
    Every 1 hour, check for stale periodic tokens.
    If not renewed for 24h, pause agent.
    """
    while True:
        await asyncio.sleep(3600)  # 1 hour

        stale_tokens = await db.query(
            UCANToken
        ).filter(
            UCANToken.renewable == True,
            UCANToken.last_renewed_at < time.time() - 86400,  # 24h
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

            # Notify admin (email, slack, etc.)
            await notify_admin(f"Agent {agent_id} auto-paused due to inactivity")
```

**Integration Points**:
- Agent heartbeat: agent must call `/auth/renew` at least once per 24h
- Agent health dashboard: show last_renewed_at for each agent
- Timeline: emit event on auto-pause (alert admin, log reason)

**Deliverable**:
- Modified UCAN token model (renewable, last_renewed_at, renewal_count)
- `/api/auth/renew` endpoint
- Background health monitor task
- 10+ test cases (renew, expiry, stale detection)
- Estimated effort: **3-4 hours**

---

## Priority 7: Immutable Audit Export (Compliance)

**Why Now?**
- HIPAA/SOC2 require tamper-proof audit trail export
- Enable audit log verification (SHA256 chain, Merkle tree, or simple HMAC)
- Export to external system (S3, syslog server) for long-term storage
- Optional premium feature (HCP Vault charges for this)

**Scope**:
- Export endpoint: `GET /api/audit/export?since={timestamp}&format=json`
- HMAC signing of export (admin verifies integrity)
- S3 sync (optional, requires AWS credentials)
- Retention policy (keep logs for 7 years for HIPAA)

**Implementation**:
```python
# In routes/audit.py
@router.get("/export")
async def export_audit_logs(
    since: float = Query(..., description="Unix timestamp"),
    format: str = Query("json", regex="^(json|csv)$"),
    auth_admin_id: str = Depends(require_admin),
):
    """
    Export audit logs since timestamp.
    Signed with HMAC for integrity verification.
    """
    logs = await db.query(AuditLog).filter(
        AuditLog.timestamp >= since
    ).all()

    if format == "json":
        data = json.dumps([log.to_dict() for log in logs])
    else:  # csv
        data = "\n".join([log.to_csv() for log in logs])

    # HMAC signature (admin can verify)
    hmac_sig = hmac.new(
        admin_audit_key.encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()

    return {
        "data": data,
        "format": format,
        "count": len(logs),
        "hmac_sha256": hmac_sig,
        "timestamp": time.time(),
    }

# Optional: S3 sync
@router.post("/export/s3")
async def export_to_s3(
    s3_bucket: str,
    auth_admin_id: str = Depends(require_admin),
):
    """
    Export all audit logs to S3 bucket.
    Requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY env vars.
    """
    logs = await db.query(AuditLog).all()

    s3 = boto3.client("s3")
    key = f"audit-logs/{time.time()}.json.gz"

    data = gzip.compress(json.dumps([log.to_dict() for log in logs]).encode())
    s3.put_object(Bucket=s3_bucket, Key=key, Body=data)

    await audit_device.log_event(AuditEvent(
        operation="audit_export_s3",
        resource_id=s3_bucket,
        result="success",
    ))

    return {"s3_key": key, "log_count": len(logs)}
```

**Integration Points**:
- Admin dashboard: audit log viewer + export buttons
- Compliance reports: generate PDF with audit trail + HMAC signature
- Scheduled export: cron job to sync to S3 daily

**Deliverable**:
- `GET /api/audit/export` endpoint (JSON + CSV)
- HMAC signing + verification tool
- Optional S3 sync endpoint
- Audit log retention policy (7 years)
- 8+ test cases (export, HMAC verify, S3 sync)
- Estimated effort: **3-4 hours**

---

## Priority 8: Pod Replication (HA)

**Why Now?**
- Federation requires high availability (can't have single point of failure)
- Vault pattern: replication is proven
- Enables disaster recovery (secondary pod as backup)
- Requires careful thought about consistency (WAL-based sync)

**Scope**:
- Replica pod mode (read-only by default)
- Delta sync: primary sends capsule changes since last sync
- Failover: if primary down, promote replica to primary
- Consistency model: eventual (replicas lag primary by seconds)

**Implementation** (Phase 2):
```python
# In federation.py
@router.post("/api/pod/replicate")
async def sync_replica(
    sync_token: str = Header(..., description="Pod authentication"),
    since_version: int = Query(..., description="Last received version"),
):
    """
    Replica pod polls primary for changes.
    Primary returns: capsules, audit logs, pool membership changes since version.
    Replica applies atomically.
    """
    # Verify sync_token is from replica pod
    replica_pod = verify_pod_token(sync_token)

    # Get delta since version
    deltas = await get_delta_since(since_version)

    return {
        "version": deltas.current_version,
        "capsules_changed": deltas.capsules,
        "audit_logs": deltas.logs,
        "pool_members_changed": deltas.members,
    }

# Replica sync loop (in replica pod lifespan)
async def replica_sync_loop(primary_pod_url: str):
    """
    Every 5 minutes, sync from primary.
    Apply changes atomically.
    """
    while True:
        try:
            response = await httpx.post(
                f"{primary_pod_url}/api/pod/replicate",
                headers={"sync_token": await get_replica_token()},
                json={"since_version": await get_local_version()},
            )
            deltas = response.json()

            # Apply atomically
            async with db.transaction():
                for capsule in deltas["capsules_changed"]:
                    await db.upsert_capsule(capsule)
                for audit_log in deltas["audit_logs"]:
                    await db.insert_audit_log(audit_log)

            await set_local_version(deltas["version"])
        except Exception as e:
            logger.error(f"Replica sync failed: {e}")

        await asyncio.sleep(300)  # 5 minutes
```

**Deliverable** (Phase 2):
- Replica pod model + state
- Delta sync endpoint + logic
- Replica sync loop
- Failover mechanism
- 10+ test cases (single delta, multi-change, consistency)
- Estimated effort: **8-10 hours** (Phase 2)

---

## Implementation Order (Recommended Timeline)

```
Week 1:
  - Priority 1: Audit Logging (6 hours)
  - Priority 2: Cascading Token Revocation (4 hours)
  - Priority 6: Token Renewal + Health Monitor (4 hours)
  [Total: 14 hours, Days 1-2]

Week 2:
  - Priority 3: Three-Tier Pod Unsealing (8 hours)
  - Priority 5: Transit Engine (5 hours)
  [Total: 13 hours, Days 3-4]

Week 3:
  - Priority 4: Policy Engine in Zig (10 hours)
  [Total: 10 hours, Day 5]

Week 4:
  - Priority 7: Audit Export (4 hours)
  - Priority 8: Pod Replication (Phase 2, 8 hours)
  [Total: 12 hours, Days 6-7]

Total: ~50 hours (2-3 weeks for full implementation)
MVP (Audit + Token Cascade + Transit): ~15 hours (2 days)
```

---

## Summary Table

| Priority | Feature | Impact | Effort | Phase |
|----------|---------|--------|--------|-------|
| 1 | Mandatory Audit Logging | Compliance, accountability | 6h | Now |
| 2 | Cascading Token Revocation | Security, agent lifecycle | 4h | Now |
| 3 | Three-Tier Pod Unsealing | Federation, audit gate | 8h | Phase 2 |
| 4 | Policy Engine (Zig) | Speed, deny-by-default | 10h | Phase 2 |
| 5 | Transit Engine | Agent encryption, rotation | 5h | Phase 2 |
| 6 | Token Renewal + Health Monitor | Agent health, auto-pause | 4h | Phase 2 |
| 7 | Audit Export | Compliance, external syslog | 4h | Phase 3 |
| 8 | Pod Replication | HA, disaster recovery | 8h | Phase 3 |

---

## Quick Start: What to Do Next

1. **Read** `/Users/jh/Code/mighty/claude-opus-hackathon/trustmesh-core/docs/vault-architecture-mapping.md` for architectural context
2. **Start with Priority 1**: Create `src/audit.py` module + `AuditLog` model
3. **Add decorator**: `@audit_required` wrapper for routes
4. **Wrap critical paths**: capsule reads, agent tasks, cross-pod queries
5. **Test**: 15+ test cases covering allowed/denied/error scenarios
6. **Move to Priority 2**: Modify UCAN token model (parent_token_id), implement cascade revocation

---

## References

- [Vault Security Model](https://developer.hashicorp.com/vault/docs/internals/security)
- [Vault Audit Logging](https://developer.hashicorp.com/vault/docs/audit)
- [Vault Leases](https://developer.hashicorp.com/vault/docs/concepts/lease)
- [Vault Policies](https://developer.hashicorp.com/vault/docs/concepts/policies)
- Project memory: `/Users/jh/.claude/projects/-Users-jh-Code-mighty-claude-opus-hackathon/memory/MEMORY.md`
