# TrustMesh: Technical Integration Roadmap

**Date**: February 18, 2026
**Audience**: Engineering & Product Teams
**Scope**: How TrustMesh plugs into A2A, MCP, and agent frameworks

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Applications                            │
│  (ChatGPT, Salesforce Agentforce, CrewAI Tasks, n8n Workflows) │
└──────────────────────┬──────────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
       v               v               v
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  CrewAI      │ │  LangGraph   │ │  Microsoft   │
│  Agents      │ │  Agents      │ │  Agent       │
│              │ │              │ │  Framework   │
└───────┬──────┘ └───────┬──────┘ └───────┬──────┘
        │ (MCP Tool)     │ (MCP Tool)     │ (MCP Tool)
        └────────────┬───┴────────────┬───┘
                     │                │
        ┌────────────v────────────────v────────────┐
        │                                            │
        │     TRUSTMESH MCP SERVER                  │
        │  (Trust Query Engine)                      │
        │                                            │
        │  Endpoints:                                │
        │  - query_capsule(agent_did, category)    │
        │  - verify_agent_identity(did)            │
        │  - get_access_scopes(agent_did)          │
        │  - audit_log_append(action, metadata)    │
        │                                            │
        │  Backed by:                                │
        │  - DID Registry (ledger-anchored)        │
        │  - Capsule Store (encrypted)              │
        │  - Audit Ledger (immutable)               │
        │  - Compliance VC Issuer                   │
        └────┬──────────────────────────────────────┘
             │
        ┌────┴──────────────────────────────────┐
        │                                        │
        v                                        v
   ┌─────────────────┐               ┌──────────────────┐
   │ TrustMesh Pods  │               │ TrustMesh Pods   │
   │ (Org A)         │               │ (Org B)          │
   │                 │               │                  │
   │ - SQLite        │   (A2A Agent  │ - SQLite         │
   │ - Zig Kernel    │    Cards +    │ - Zig Kernel     │
   │ - Compliance    │    Protocols) │ - Compliance     │
   │   Registry      │               │   Registry       │
   └─────────────────┘               └──────────────────┘
        │                                  │
        └──────────────────┬───────────────┘
                           │
                    (Federated Pool)
                    (Ghost Agents)
                    (VC Sharing)
```

---

## Integration Points & Protocol Specifications

### 1. MCP Server Integration (Primary)

**Purpose**: Enable any agent framework to query TrustMesh via MCP.

#### 1.1 MCP Server Implementation

```python
# src/mcp_server.py (NEW)

from typing import Any
from mcp.server import Server
from mcp.types import Tool, TextContent, ToolResult

server = Server("trustmesh-mcp")

# Register tools available to MCP clients
@server.call_tool()
async def query_capsule(
    agent_did: str,
    category: str,
    keywords: str | None = None,
    trust_level: str = "network"  # "public", "network", "private"
) -> ToolResult:
    """
    Query accessible capsules as a specific agent.

    Args:
        agent_did: Requesting agent's DID (e.g., "did:trustmesh:agent-123")
        category: Capsule category (e.g., "medical_records", "financial")
        keywords: Search keywords (optional)
        trust_level: Max trust level to expose (default: "network")

    Returns:
        List of capsules matching query + access criteria
        Each capsule includes: {id, title, category, summary, access_level, owner}
    """
    # 1. Verify agent_did is valid
    agent = await verify_agent_identity(agent_did)
    if not agent:
        return ToolResult(
            content=[TextContent(type="text", text="Unauthorized: Invalid agent DID")],
            is_error=True
        )

    # 2. Resolve trust level for this agent
    trust_level_resolved = await resolve_trust_level(
        requesting_agent_did=agent_did,
        resource_owner=None  # Query all owners
    )

    # 3. Query capsules accessible at this trust level
    capsules = await get_accessible_capsules(
        requesting_agent_did=agent_did,
        category=category,
        keywords=keywords,
        trust_level=trust_level_resolved
    )

    # 4. Apply trust-based filtering + audit
    filtered = [
        {
            "id": c.id,
            "title": c.title,
            "category": c.category,
            "summary": c.summary,  # Truncated for security
            "access_level": c.access_level,
            "owner_pod": c.owner_pod_url
        }
        for c in capsules
    ]

    # 5. Log query in audit trail
    await audit_log_append(
        action="capsule_query",
        agent_did=agent_did,
        resource="capsule",
        category=category,
        result_count=len(filtered),
        trust_level_applied=trust_level_resolved
    )

    return ToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(filtered)
        )]
    )

@server.call_tool()
async def verify_agent_identity(agent_did: str) -> ToolResult:
    """
    Verify agent DID and retrieve capability claims.

    Returns: Agent metadata + verifiable credentials (VCs)
    """
    # 1. Lookup agent in DID registry
    agent_record = await trustmesh_did_registry.resolve(agent_did)
    if not agent_record:
        return ToolResult(
            content=[TextContent(type="text", text="Not found")],
            is_error=True
        )

    # 2. Retrieve associated VCs (compliance, capabilities)
    vcs = await get_agent_verifiable_credentials(agent_did)

    # 3. Validate VC signatures (issuer, timestamp, expiry)
    valid_vcs = [vc for vc in vcs if await validate_vc_signature(vc)]

    result = {
        "did": agent_did,
        "name": agent_record.name,
        "type": agent_record.type,  # "personal_agent", "enterprise_agent", "service_agent"
        "pod_url": agent_record.pod_url,
        "capabilities": agent_record.capabilities,
        "verifiable_credentials": [
            {
                "issuer": vc.issuer,
                "claim": vc.claim,  # e.g., "HIPAA_compliant"
                "issued_at": vc.issued_at,
                "expires_at": vc.expires_at,
                "signature_valid": True
            }
            for vc in valid_vcs
        ]
    }

    return ToolResult(
        content=[TextContent(type="text", text=json.dumps(result))]
    )

@server.call_tool()
async def get_access_scopes(agent_did: str) -> ToolResult:
    """
    Retrieve scopes (permissions) granted to agent.

    Returns: List of {resource_type, action, conditions}
    """
    scopes = await access_control.get_agent_scopes(agent_did)

    result = [
        {
            "resource_type": scope.resource_type,  # "capsule", "agent", "pool"
            "action": scope.action,  # "read", "write", "delete", "query"
            "resource_id": scope.resource_id,
            "conditions": scope.conditions  # {trust_level: "network", category: "medical"}
        }
        for scope in scopes
    ]

    return ToolResult(
        content=[TextContent(type="text", text=json.dumps(result))]
    )

@server.call_tool()
async def audit_log_append(
    action: str,
    agent_did: str,
    resource_type: str,
    resource_id: str | None = None,
    result: str | None = None,
    metadata: dict | None = None
) -> ToolResult:
    """
    Append entry to immutable audit trail.

    Used by agent frameworks to log decisions made using TrustMesh data.
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,  # "query_capsule", "access_denied", "policy_violation"
        "agent_did": agent_did,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "result": result,  # "success", "access_denied", "not_found"
        "metadata": metadata or {}
    }

    # Append to immutable ledger (SQLite WAL + signature)
    await audit_ledger.append(log_entry)

    return ToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps({"status": "logged"})
        )]
    )

# Lifecycle
@server.lifespan
async def lifespan(server: Server):
    async with server:
        # Initialize TrustMesh runtime
        await trustmesh_engine.initialize()
        yield
        await trustmesh_engine.shutdown()

if __name__ == "__main__":
    server.run_stdio()
```

#### 1.2 Framework Integration Examples

**CrewAI Integration** (`crewai_trustmesh.py`):

```python
from crewai import Agent, Task, Crew
from trustmesh_mcp_client import TrustMeshTool

# Create TrustMesh tools
trustmesh = TrustMeshTool(
    mcp_server_url="http://localhost:3001",  # TrustMesh MCP server
    agent_did="did:trustmesh:crewai-task-123"
)

# Add to agent
research_agent = Agent(
    role="healthcare-researcher",
    goal="Analyze medical records securely",
    tools=[
        trustmesh.query_capsule,
        trustmesh.verify_agent_identity,
        trustmesh.get_access_scopes
    ]
)

@task
def analyze_records():
    """Query medical capsules via TrustMesh."""

    # CrewAI agent calls: trustmesh.query_capsule(...)
    # MCP server resolves trust + applies policy
    # Audit logged automatically
```

**LangGraph Integration** (via MCP):

```python
from langgraph.graph import StateGraph
from langchain_community.tools.mcp import MCPTool

# Initialize MCP client pointing to TrustMesh
mcp_client = MCPTool(
    server_uri="stdio:///Users/jh/trustmesh-mcp-server"
)

# Graph node using TrustMesh
async def query_medical_data(state):
    capsules = await mcp_client.call_tool(
        tool_name="query_capsule",
        agent_did="did:trustmesh:langgraph-node-456",
        category="medical_records",
        keywords="patient_summary",
        trust_level="network"
    )

    state["medical_data"] = capsules
    return state

# OpenAI Agents SDK (Feb 2026):
# agents.sdk supports MCP tools natively
```

---

### 2. A2A Protocol Extension (Secondary Integration)

**Purpose**: Extend A2A agent cards with TrustMesh trust + compliance metadata.

#### 2.1 A2A Agent Card Extension

```json
{
  "id": "did:example:agent-healthcare-processor",
  "name": "Healthcare Data Processor",
  "description": "Processes patient medical records securely",
  "type": "service",

  // Standard A2A fields
  "endpoints": [
    {
      "type": "http",
      "url": "https://healthcare-pod.example.com/api/agent",
      "auth": "bearer_token"
    }
  ],
  "capabilities": [
    {
      "name": "query_records",
      "description": "Query medical records by patient ID",
      "input_schema": {
        "type": "object",
        "properties": {
          "patient_id": {"type": "string"},
          "data_types": {"type": "array"}
        }
      }
    }
  ],

  // ★ NEW: TrustMesh Extension
  "trustmesh": {
    "version": "1.0",

    // Identity + Compliance
    "pod_did": "did:trustmesh:pod-healthcare-org",
    "trust_tier": "enterprise",

    // Verifiable Credentials (cryptographically signed)
    "compliance_credentials": [
      {
        "credential_type": "HIPAA_compliant",
        "issuer": "did:trustmesh:auditor-1",
        "issued": "2025-12-01T00:00:00Z",
        "expires": "2026-12-01T00:00:00Z",
        "signature": "base64_ed25519_signature"
      },
      {
        "credential_type": "SOC2_Type2",
        "issuer": "did:trustmesh:auditor-2",
        "issued": "2025-06-01T00:00:00Z",
        "expires": "2026-06-01T00:00:00Z",
        "signature": "base64_ed25519_signature"
      }
    ],

    // Access scopes (what data can this agent access?)
    "access_scopes": [
      {
        "resource_type": "capsule",
        "category": "medical_records",
        "action": "read",
        "conditions": {
          "trust_level": ["network", "private"],
          "data_classification": ["patient_summary", "vital_signs"]
        }
      },
      {
        "resource_type": "capsule",
        "category": "audit_logs",
        "action": "read"
      }
    ],

    // Federation info (if multi-org)
    "federation_pool": "did:trustmesh:pool-healthcare-network",
    "federation_role": "member",

    // Trust policy (how should other agents trust this agent?)
    "trust_policy": {
      "minimum_trust_level": "network",
      "require_compliance_credentials": true,
      "rate_limit": "1000_req_per_hour",
      "data_minimization": true
    }
  }
}
```

#### 2.2 A2A Discovery Integration

When agent A discovers agent B via A2A discovery:

```python
# In agent framework
async def discover_and_connect_to_agent(agent_id: str):
    # 1. Fetch agent card via A2A discovery
    agent_card = await a2a_discovery.get_agent_card(agent_id)

    # 2. Extract TrustMesh extension
    trustmesh_ext = agent_card.get("trustmesh", {})

    # 3. Verify compliance credentials
    if trustmesh_ext.get("compliance_credentials"):
        for cred in trustmesh_ext["compliance_credentials"]:
            is_valid = await verify_vc_signature(cred)
            if not is_valid:
                logger.warn(f"Invalid VC: {cred['credential_type']}")

    # 4. Resolve access scopes (what can we ask this agent for?)
    scopes = trustmesh_ext.get("access_scopes", [])

    # 5. Apply local trust policy
    trust_decision = await trustmesh.evaluate_trust(
        target_agent_did=agent_card["id"],
        scopes=scopes,
        compliance_credentials=trustmesh_ext.get("compliance_credentials", [])
    )

    # 6. If trusted, establish connection + log in audit trail
    if trust_decision.allowed:
        await establish_a2a_connection(agent_card)
        await audit_log_append(
            action="a2a_connection_established",
            agent_did=agent_card["id"],
            trust_level=trust_decision.trust_level,
            compliance_status=trust_decision.compliance_status
        )
```

---

### 3. OpenAI Agents SDK Guardrail Integration

**Purpose**: Validate agent data access against TrustMesh policy.

#### 3.1 Guardrail Implementation

```python
# In OpenAI Agents SDK (native support for guardrails)

from openai.lib.agents import Agent, Guardrail
from trustmesh_client import TrustMeshClient

trustmesh = TrustMeshClient(
    pod_url="http://localhost:8000",
    agent_did="did:trustmesh:openai-agent-789"
)

class TrustMeshAccessGuardrail(Guardrail):
    """
    Validates agent tool calls against TrustMesh access policy.

    Runs BEFORE tool execution (blocking mode) to prevent:
    - Unauthorized data access
    - Compliance violations
    - Policy breaches
    """

    def validate_before_tool_call(self, tool_name: str, tool_input: dict) -> bool:
        """
        Called before agent invokes a tool.
        Return False to block execution.
        """

        # 1. Check if this tool accesses sensitive data
        if tool_name in ["query_db", "fetch_api", "search_documents"]:

            # 2. Resolve what data the tool will access
            resource_type = tool_input.get("resource_type", "")
            category = tool_input.get("category", "")

            # 3. Query TrustMesh: does this agent have access?
            access_check = trustmesh.check_access(
                agent_did=self.agent_did,
                resource_type=resource_type,
                category=category
            )

            # 4. Block if unauthorized
            if not access_check.allowed:
                self.log_denial(
                    tool_name=tool_name,
                    agent_did=self.agent_did,
                    reason=access_check.denial_reason
                )
                raise PermissionError(
                    f"Agent {self.agent_did} not authorized to access {category}"
                )

        return True

    def validate_after_tool_call(self, tool_name: str, result: Any) -> Any:
        """
        Called after tool execution.
        Can filter/redact sensitive data in result.
        """

        # 1. If result contains PII, redact based on trust level
        trust_level = trustmesh.resolve_trust_level(self.agent_did)

        if trust_level == "public":
            # Redact names, emails, PHI from result
            result = self._redact_pii(result)

        # 2. Log access in audit trail
        trustmesh.audit_log_append(
            action="tool_executed",
            agent_did=self.agent_did,
            tool_name=tool_name,
            result_size_bytes=len(str(result))
        )

        return result

# Register guardrail with agent
agent = Agent(
    model="gpt-4",
    tools=[db_tool, api_tool],
    guardrails=[TrustMeshAccessGuardrail(agent_did="...")]
)
```

---

### 4. Compliance VC Issuer

**Purpose**: TrustMesh issues verifiable credentials for pod compliance (HIPAA, SOC2, etc.).

#### 4.1 VC Issuance Endpoint

```python
# POST /api/compliance/issue-vc

@router.post("/compliance/issue-vc")
async def issue_compliance_vc(
    request: ComplianceVCRequest,
    auth_user_id: str = Depends(get_current_user_id)
) -> dict:
    """
    Issue a verifiable credential attesting to pod compliance.

    Only authorized parties (auditors, admins) can issue VCs.
    """

    # 1. Verify issuer authority
    issuer_did = await did_registry.get_user_did(auth_user_id)
    if not issuer_did.can_issue_compliance_vc:
        raise PermissionError("Not authorized to issue compliance VCs")

    # 2. Build VC
    vc_payload = {
        "@context": ["https://www.w3.org/2018/credentials/v1"],
        "type": ["VerifiableCredential"],
        "issuer": issuer_did.did,
        "issuanceDate": datetime.utcnow().isoformat(),
        "expirationDate": (
            datetime.utcnow() + timedelta(days=365)
        ).isoformat(),
        "credentialSubject": {
            "id": request.pod_did,
            "compliantWith": request.compliance_type,  # "HIPAA", "SOC2", "GDPR"
            "auditedBy": request.auditor_name,
            "auditDate": request.audit_date,
            "scope": request.scope  # e.g., "all_pod_operations"
        }
    }

    # 3. Sign VC with issuer's private key
    signature = await sign_vc(vc_payload, issuer_did.private_key)

    vc_signed = {
        "payload": vc_payload,
        "proof": {
            "type": "Ed25519Signature2020",
            "created": datetime.utcnow().isoformat(),
            "verificationMethod": f"{issuer_did.did}#signing-key",
            "signatureValue": signature
        }
    }

    # 4. Store VC
    vc_id = await vc_store.save(vc_signed)

    # 5. Log in audit trail
    await audit_log_append(
        action="vc_issued",
        issuer_did=issuer_did.did,
        subject_pod_did=request.pod_did,
        vc_type=request.compliance_type
    )

    return {
        "vc_id": vc_id,
        "vc": vc_signed,
        "status": "issued"
    }
```

#### 4.2 VC Verification

```python
async def verify_vc_signature(vc: dict) -> bool:
    """
    Verify VC signature using issuer's public key from DID registry.
    """

    # 1. Extract issuer DID from VC
    issuer_did = vc["payload"]["issuer"]

    # 2. Resolve issuer DID → get public key
    issuer_record = await did_registry.resolve(issuer_did)
    issuer_public_key = issuer_record.public_key

    # 3. Verify signature
    signature = vc["proof"]["signatureValue"]
    payload_bytes = json.dumps(vc["payload"]).encode()

    is_valid = ed25519.verify(
        message=payload_bytes,
        signature=signature,
        public_key=issuer_public_key
    )

    # 4. Check expiration
    if datetime.fromisoformat(vc["payload"]["expirationDate"]) < datetime.utcnow():
        return False

    return is_valid
```

---

### 5. Federated Pool Coordination

**Purpose**: Enable multiple orgs to form trust pools for agent collaboration.

#### 5.1 Federation Architecture

```python
# src/routes/federation.py (ENHANCED)

@router.post("/api/federation/pools")
async def create_federation_pool(
    request: CreateFederationPoolRequest,
    auth_user_id: str = Depends(get_current_user_id)
) -> dict:
    """
    Create a federated pool of trusted pods.

    Members can query each other's capsules at "network" trust level.
    """

    # 1. Verify creator authority
    creator_pod = await get_user_pod(auth_user_id)

    # 2. Create pool DID
    pool_did = did_registry.generate_pool_did(
        name=request.pool_name,
        creator=creator_pod.did
    )

    # 3. Store pool metadata
    pool = FederationPool(
        did=pool_did,
        name=request.pool_name,
        description=request.description,
        pool_type=request.pool_type,  # "healthcare_network", "bank_consortium", etc.
        created_at=datetime.utcnow(),
        members=[
            {
                "pod_did": creator_pod.did,
                "pod_name": creator_pod.name,
                "pod_url": creator_pod.url,
                "trust_level": "full"  # Creator has full trust
            }
        ],
        policies={
            "default_trust_level": "network",
            "require_compliance_credentials": request.require_compliance,
            "allowed_categories": request.allowed_categories
        }
    )

    await db.pools.insert(pool)

    # 4. Generate pool invite tokens (shareable with other org admins)
    invite_token = await generate_pool_invite_token(
        pool_did=pool_did,
        max_members=request.max_members,
        expires_in=timedelta(days=30)
    )

    # 5. Log in audit
    await audit_log_append(
        action="federation_pool_created",
        pool_did=pool_did,
        creator_pod=creator_pod.did
    )

    return {
        "pool_did": pool_did,
        "pool_name": request.pool_name,
        "invite_token": invite_token,
        "status": "created"
    }

@router.post("/api/federation/pools/{pool_did}/join")
async def join_federation_pool(
    pool_did: str,
    request: JoinFederationPoolRequest,
    auth_user_id: str = Depends(get_current_user_id)
) -> dict:
    """
    Join an existing federation pool via invite token.

    Joining pod becomes "member" with network-level trust.
    """

    # 1. Validate invite token
    token_valid = await validate_pool_invite_token(
        pool_did=pool_did,
        token=request.invite_token
    )
    if not token_valid:
        raise ValueError("Invalid or expired pool invite token")

    # 2. Get joining pod
    joining_pod = await get_user_pod(auth_user_id)

    # 3. Create ghost user in pool's pod (for cross-org visibility)
    ghost_user = await create_ghost_user(
        username=f"remote:{joining_pod.admin_username}@{joining_pod.url}",
        remote_pod_url=joining_pod.url,
        remote_did=joining_pod.did
    )

    # 4. Add to pool membership
    pool = await db.pools.find_one({"did": pool_did})
    pool.members.append({
        "pod_did": joining_pod.did,
        "pod_name": joining_pod.name,
        "pod_url": joining_pod.url,
        "trust_level": "member",
        "ghost_user_id": ghost_user.id,
        "joined_at": datetime.utcnow()
    })
    await db.pools.update(pool)

    # 5. Create reverse connection (so joining pod can query pool creator)
    # This is done asynchronously to avoid deadlock
    asyncio.create_task(
        establish_federated_connections(pool, joining_pod)
    )

    # 6. Log
    await audit_log_append(
        action="pod_joined_federation_pool",
        pool_did=pool_did,
        joining_pod=joining_pod.did
    )

    return {
        "pool_did": pool_did,
        "status": "joined",
        "trust_level": "member"
    }
```

#### 5.2 Cross-Pool Queries

```python
# When agent from Org A queries Org B's capsules (both in federation pool)

async def query_accessible_capsules_federated(
    requesting_agent_did: str,
    category: str,
    keywords: str | None = None
) -> List[Capsule]:
    """
    Query capsules across federated pool.

    1. Local capsules (requesting_agent's pod)
    2. Remote capsules (other pods in federation pool)
    """

    # 1. Get requesting agent's pod
    requesting_pod = await did_registry.resolve_pod(requesting_agent_did)

    # 2. Get requesting pod's federation pools
    pools = await db.pools.find(
        {"members": {"pod_did": requesting_pod.did}}
    )

    # 3. Query locally accessible capsules
    local_capsules = await query_accessible_capsules_local(
        requesting_agent_did=requesting_agent_did,
        category=category,
        keywords=keywords
    )

    # 4. For each pool, query member pods
    federated_capsules = []
    for pool in pools:
        for member in pool.members:
            if member.pod_did == requesting_pod.did:
                continue  # Skip self

            # 5. Make remote query via A2A protocol
            remote_results = await query_remote_pod_via_a2a(
                target_pod_url=member.pod_url,
                requesting_agent_did=requesting_agent_did,
                requesting_pod_did=requesting_pod.did,
                category=category,
                keywords=keywords,
                trust_level="network",  # Federated member trust
                pool_did=pool.did
            )

            federated_capsules.extend(remote_results)

    # 6. Merge + deduplicate
    all_capsules = local_capsules + federated_capsules

    return all_capsules
```

---

## Implementation Phases

### Phase 1: Q1 2026 (MVP)
- ✅ MCP server (query_capsule, verify_identity, get_access_scopes)
- ✅ A2A extension spec (proposed to AAIF)
- ✅ Basic VC issuer
- ~500 lines of Python + Zig

### Phase 2: Q2–Q3 2026 (Framework Integration)
- ✅ CrewAI tool library
- ✅ LangGraph integration (via MCP)
- ✅ OpenAI Agents SDK guardrail
- ✅ HIPAA BAA compliance
- ~2000 lines of Python

### Phase 3: Q4 2026+ (Federation)
- ✅ Federation pool coordinator
- ✅ Ghost agent support
- ✅ Multi-org audit trails
- ✅ Agent registry (agents.trustmesh.io)
- ~3000 lines of Python + TypeScript

---

## Testing & Validation

### Unit Tests
- VC signature validation (Ed25519)
- DID resolution
- Trust level calculation
- Policy evaluation

### Integration Tests
- MCP server with CrewAI agent
- A2A agent card parsing + validation
- Federated pool queries
- Cross-org audit trail

### Security Tests
- VC tampering detection
- DID spoofing prevention
- Cross-pod access validation
- Audit trail integrity

---

## Key Implementation Details

### Security Considerations
1. **Ed25519 Signing**: All VCs + audit entries signed
2. **SQLite WAL**: Immutable audit ledger with checksums
3. **Zig Integration**: Crypto ops in Zig (already exists)
4. **HMAC-based Integrity**: Audit trail tamper-detection

### Performance Considerations
1. **MCP Server Caching**: Cache DID → Pod mappings
2. **Local Query Optimization**: Use FTS5 for category + keyword search
3. **Async Federated Queries**: Parallel remote pod queries (asyncio)
4. **Rate Limiting**: Per-agent, per-pod, per-pool

### Interoperability
1. **A2A Standard**: 50+ vendor support (follow spec closely)
2. **MCP Standard**: 13K+ servers (follow spec closely)
3. **W3C VCs**: Use standard @context + proof format
4. **DIDs**: Use `did:trustmesh:` scheme (self-issued, verifiable)

---

## Success Metrics

| Metric | Target (6mo) | Target (12mo) |
|--------|--------------|--------------|
| MCP Server Downloads | 1K | 10K |
| CrewAI Integration Users | — | 500 |
| Federation Pool Pilots | 0 | 3 |
| Cross-Org Queries/Day | — | 10K+ |
| Audit Log Entries | — | 1M+ |
| HIPAA Certifications | — | 3 |

---

## Dependencies & External Services

- **AAIF** (for A2A spec): Partner relationship
- **LangChain** (for MCP registry): Free listing
- **Anthropic** (MCP standardization): Partnership
- **OpenAI** (Agents SDK guardrail API): Partnership
- **Auditing firms** (HIPAA/SOC2 certification): Vendor relationship

---

## Risks & Mitigation

| Risk | Mitigation |
|------|-----------|
| A2A/MCP spec changes | Backwards compatibility, semantic versioning |
| MCP server bottleneck | Horizontal scaling, caching layer |
| Cross-pod latency | Async queries, federation pooling |
| Compliance VC fraud | Multi-sig VCs, auditor consortium |
| DID registry attacks | Ledger-based DID resolution (immutable) |

