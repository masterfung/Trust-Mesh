# Trust Architecture: How TrustMesh Enforces Trust

## The Core Problem

Today's AI agents operate in a binary world: either they share everything or nothing. There's no concept of:

- "Share my grandma's medication schedule with my family, but not my coworker"
- "Share my work project timeline with my team, but not my family"
- "Keep my private journal entries hidden from everyone"

TrustMesh solves this with a **three-tier trust model** backed by human-approved connections, user-created networks, and Opus 4.6 reasoning.

---

## 1. Trust Tiers

### Tier Model

```
┌─────────────────────────────────────────────────────┐
│                    PRIVATE                           │
│  Only the owner's agent can see these capsules.      │
│  Example: Molly's journal about grandma's prognosis  │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │                  NETWORK                         │ │
│  │  Visible to members of specified networks.       │ │
│  │  Example: Grandma's care routine → "The Johnsons"│ │
│  │                                                  │ │
│  │  ┌─────────────────────────────────────────────┐ │ │
│  │  │                PUBLIC                        │ │ │
│  │  │  Visible to anyone who queries.              │ │ │
│  │  │  Example: "Peter is a licensed electrician"  │ │ │
│  │  └─────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Trust Resolution Algorithm

```python
def resolve_trust_level(from_user_id: str, to_user_id: str) -> tuple[str, list[Network]]:
    """
    Determine the trust tier between two users.

    Returns:
        (trust_level, shared_networks)
        trust_level is one of: "public", "network", "private"
        shared_networks is the list of networks both users belong to
    """
    # Step 1: Check if they're the same user (owner querying own agent)
    if from_user_id == to_user_id:
        return ("private", [])  # Full access to own vault

    # Step 2: Check if they have an accepted connection
    connection = get_accepted_connection(from_user_id, to_user_id)
    if not connection:
        return ("public", [])  # No connection = public only

    # Step 3: Find shared networks
    from_networks = get_user_network_ids(from_user_id)
    to_networks = get_user_network_ids(to_user_id)
    shared_network_ids = from_networks & to_networks

    if shared_network_ids:
        shared = get_networks_by_ids(shared_network_ids)
        return ("network", shared)

    # Connected but no shared networks = still public tier
    return ("public", [])
```

### Capsule Visibility Rules

Given a trust level and shared networks, which capsules can the requester's query access?

| Capsule Tier | Public Trust | Network Trust | Private Trust (Owner Only) |
|-------------|-------------|---------------|---------------------------|
| `public` | Visible | Visible | Visible |
| `network` (shared to Network X) | Hidden | Visible (if requester is in Network X) | Visible |
| `network` (shared to Network Y) | Hidden | Hidden (if requester is NOT in Network Y) | Visible |
| `private` | Hidden | Hidden | Visible |

```python
def get_accessible_capsules(owner_id, trust_level, shared_networks):
    """Return capsules accessible at the given trust level."""
    if trust_level == "private":
        # Owner sees everything
        return get_all_active_capsules(owner_id)

    elif trust_level == "network":
        # Public capsules + capsules shared to overlapping networks
        network_ids = [n.id for n in shared_networks]
        public = get_capsules_by_tier(owner_id, "public")
        network = get_capsules_for_networks(owner_id, network_ids)
        return public + network

    else:  # "public"
        return get_capsules_by_tier(owner_id, "public")
```

---

## 2. Connection Model

### How Connections Work

Connections in TrustMesh are **explicit, bidirectional, and human-approved**:

```
1. Alice searches for Bob (Bob must be discoverable)
2. Alice sends connection request with a message
3. Bob reviews the request and MANUALLY approves or declines
4. If approved: bidirectional connection is established
5. Now they can query each other's public capsules
6. To access network-tier capsules, they must share a network
```

### Connection States

```
┌─────────┐     send request     ┌─────────┐     accept     ┌──────────┐
│  None    │ ──────────────────► │ Pending  │ ──────────────► │ Accepted │
└─────────┘                      └─────────┘                  └──────────┘
                                       │
                                       │ decline
                                       ▼
                                 ┌──────────┐
                                 │ Declined │
                                 └──────────┘
```

### Why Manual Approval Matters

This is a deliberate design choice, not a limitation:

1. **Trust is earned**: Unlike social media's "follow" model, connections represent actual trust
2. **Human judgment**: Humans decide who to trust, agents enforce those decisions
3. **No auto-discovery attack**: Malicious agents can't auto-connect to scrape knowledge
4. **Auditability**: Every connection has a human decision behind it

---

## 3. Network Model

### Network Types

| Type | Description | Example |
|------|------------|---------|
| `family` | Biological or chosen family | "The Johnsons" |
| `team` | Work/project teams | "TechCorp PM Team" |
| `friends` | Social circles | "Book Club" |
| `custom` | Any grouping | "Grandma's Care Team" |

### Network Lifecycle

```
1. Owner creates network (becomes owner + first member)
2. Owner adds connected users as members
   - User must be connected to owner first
   - Member receives the network encryption key (re-encrypted for their vault)
3. Members can now see capsules shared to this network
4. Owner can remove members at any time
   - Removed member loses access immediately
   - Network key should be rotated (production)
```

### Network Key Management

```
Network Creation:
  1. Generate random AES-256-GCM network_key
  2. Encrypt network_key with owner's vault master key → store

Adding a Member:
  1. Decrypt network_key using owner's vault master key
  2. Re-encrypt network_key with member's vault master key
  3. Store the re-encrypted key for the member

Capsule Encryption:
  - Capsules with tier="network" are encrypted with the network_key
  - Any member with the network_key can decrypt
  - Members without the key (non-members) cannot access
```

---

## 4. Token Gating & Capability Tokens

### Current Implementation (Hackathon)

For the hackathon, we use **session-based authentication** with httpOnly cookies:

```
Login → Server creates session → Set httpOnly cookie
Query → Cookie sent automatically → Server validates session → Trust resolution
```

### Future: Capability Tokens (Biscuit-style)

For production, TrustMesh would use attenuable capability tokens:

```
Token Properties:
  - Issuer: TrustMesh authorization server
  - Subject: The requesting agent/user
  - Capabilities: What they can do
  - Attenuation: Each delegation can only RESTRICT, never expand
  - Expiry: Time-limited by default
  - Audience: Bound to specific resource (RFC 8707)
```

#### Biscuit Tokens

Biscuit tokens are the best fit for agent delegation:

```
Token Structure:
  Block 0 (Authority): {user: "kyle", can: ["query"], networks: ["techcorp-pm"]}
  Block 1 (Attenuation): {restrict: read_only, max_queries: 10}
  Block 2 (Attenuation): {restrict: capsule_types: ["schedule", "skill"]}

Verification:
  - Each block is signed with the previous block's key
  - Blocks can only ADD restrictions, never remove them
  - Token is verified locally (no server roundtrip needed)
  - Expired tokens are rejected without network call
```

#### Delegation Example

```
Scenario: Kyle needs temporary access to grandma's care routine

1. Molly creates a capability token:
   {user: "kyle", networks: ["the-johnsons"], expires: "2025-02-21", purpose: "grandma-care"}

2. Kyle's agent uses this token to query Molly's agent:
   - Token grants network-level access to "The Johnsons" capsules
   - Trust resolution sees Kyle as a network member (via token)
   - Kyle can access grandma's care routine

3. Token expires after Molly's trip:
   - Kyle can no longer access family capsules
   - No manual cleanup needed
```

#### UCAN (Decentralized Alternative)

UCAN (User-Controlled Authorization Networks) uses DIDs for delegation chains:

```
did:key:alice → grants(query, network:family) → did:key:bob
did:key:bob → attenuates(query, network:family, read_only) → did:key:charlie

- No central authorization server needed
- Delegation chain is self-verifiable
- Each hop can only restrict permissions
```

### Comparison of Token Approaches

| Feature | Session Cookies | Biscuit | UCAN | OAuth 2.1 |
|---------|----------------|---------|------|-----------|
| Delegation | No | Yes (attenuable) | Yes (DID chains) | Limited (refresh tokens) |
| Offline Verification | No | Yes | Yes | No (requires introspection) |
| Revocation | Server-side (fast) | Revocation list | Revocation DID | Token introspection |
| Complexity | Low | Medium | High | Medium |
| Standards Maturity | High | Growing | Growing | High |
| Best For | Web apps (hackathon) | Agent delegation | Decentralized systems | External tool integration |

---

## 5. Policy Engines (Future)

For production-grade access control, TrustMesh could integrate a policy engine:

### OPA (Open Policy Agent)

```rego
# TrustMesh access policy in Rego
package trustmesh.access

default allow = false

# Owner always has access
allow {
    input.requester_id == input.capsule_owner_id
}

# Public capsules are accessible to anyone
allow {
    input.capsule_tier == "public"
}

# Network capsules require shared network membership
allow {
    input.capsule_tier == "network"
    input.trust_level == "network"
    some network_id in input.capsule_network_ids
    network_id in input.shared_network_ids
}

# Block archived capsules
deny {
    input.capsule_is_archived == true
}

# Block expired capsules
deny {
    input.capsule_expires_at != null
    time.now_ns() > input.capsule_expires_at
}
```

### Cedar (Amazon)

```cedar
// TrustMesh access policy in Cedar
permit(
  principal in TrustMesh::Network::"the-johnsons",
  action == TrustMesh::Action::"query",
  resource in TrustMesh::CapsuleTier::"network"
) when {
  resource.network_ids.contains(principal.network_id)
};

forbid(
  principal,
  action,
  resource
) when {
  resource.is_archived == true
};
```

---

## 6. Trust Flow: End-to-End Query

Here's the complete trust enforcement path for a query:

```
Bill asks Jane's agent: "Where did Jane leave her wallet?"

1. AUTHENTICATION
   Bill's session cookie → validate_session() → Bill's user_id

2. TRUST RESOLUTION
   resolve_trust_level(bill.id, jane.id)
   → Check connection: Bill ↔ Jane (accepted) ✓
   → Check shared networks: Both in "The Johnsons" ✓
   → Result: trust_level="network", shared_networks=["The Johnsons"]

3. CITADEL INPUT SCAN
   citadel_scan_input("Where did Jane leave her wallet?")
   → heuristic_score: 0.05 (benign question)
   → decision: ALLOW

4. CAPSULE ACCESS FILTERING
   get_accessible_capsules(jane.id, "network", ["The Johnsons"])
   → Returns: public capsules + capsules shared to "The Johnsons"
   → Includes: "Jane's Lost Wallet" (network tier, shared to The Johnsons)
   → Excludes: "Jane's Diary" (private tier)

5. SEMANTIC RETRIEVAL
   retrieve_relevant_capsules(question, accessible_capsule_ids, top_k=5)
   → ChromaDB vector search over accessible capsules
   → Top result: "Jane's Lost Wallet" (high semantic relevance)

6. OPUS 4.6 AGENT REASONING
   Agent receives: question + trust context + relevant capsules
   Agent reasons: "Bill is in the family network, this capsule is shared to family"
   Agent responds: "Jane left her wallet on the kitchen counter before school Tuesday.
                    It has her school ID, library card, and $23."

7. CITADEL OUTPUT SCAN
   citadel_scan_output(response)
   → Check for: credential leaks, PII overexposure, data exfiltration patterns
   → Result: safe

8. AUDIT LOG
   Record: {
     query_id, from_user: bill, to_user: jane,
     question, trust_level: "network",
     shared_networks: ["The Johnsons"],
     capsules_accessed: ["jane-lost-wallet"],
     citadel_input_score: 0.05,
     citadel_output_safe: true,
     decision: "allowed",
     response_preview: "Jane left her wallet...",
     latency_ms: 1847
   }

9. RESPONSE TO BILL
   {
     "decision": "allowed",
     "response": "Jane left her wallet on the kitchen counter...",
     "trust_level": "network",
     "shared_networks": ["The Johnsons"],
     "latency_ms": 1847
   }
```

### Same Query from Kyle

```
Kyle asks Jane's agent: "Where did Jane leave her wallet?"

1. AUTHENTICATION: Kyle's session → Kyle's user_id

2. TRUST RESOLUTION:
   → Check connection: Kyle ↔ Jane — NOT CONNECTED
   → Result: trust_level="public", shared_networks=[]

3. CITADEL INPUT SCAN: ALLOW (benign question)

4. CAPSULE ACCESS FILTERING:
   → Returns: ONLY public capsules
   → "Jane's Lost Wallet" is network-tier → NOT ACCESSIBLE
   → Only "Jane's Public Bio" available

5. SEMANTIC RETRIEVAL:
   → No wallet-related public capsules found
   → Returns: "Jane's Public Bio" (low relevance to wallet question)

6. OPUS 4.6 AGENT REASONING:
   Agent reasons: "Kyle has public-only access. I have no wallet information
                   in the public capsules. I should not reveal private info."
   Agent responds: "I don't have that information. I can tell you that Jane
                    is a 10th grader at Lincoln High who plays varsity soccer."

7. CITADEL OUTPUT SCAN: safe

8. AUDIT LOG: decision="allowed" (query was allowed, but agent chose not to
   reveal info it doesn't have access to at this trust level)

9. RESPONSE: Public info only. Wallet location protected.
```
