# Knowledge Sharing Protocol: How Internal Stakeholders Discover, Access, and Govern Shared Knowledge

## The Core Question

When Molly shares "Grandma Rose's Care Routine" to the Johnson family network, what actually happens? How does Peter know it exists? How does he access it? What if Molly wants to revoke access? What if Peter needs to temporarily share it with a home aide?

This document defines the full lifecycle of knowledge sharing in TrustMesh, with UCAN (User Controlled Authorization Networks) as the authorization backbone.

---

## 1. Positioning: TrustMesh as an Internal Sharing Platform

TrustMesh is **not** a social network. It's an **internal knowledge sharing platform** where:

```
┌─────────────────────────────────────────────────────────────┐
│                    TrustMesh Core Value                      │
│                                                             │
│   "Agents hold knowledge. Networks define trust boundaries. │
│    UCAN tokens govern access. Vaults keep it encrypted."    │
│                                                             │
│   Three pillars:                                            │
│   ┌───────────┐  ┌───────────┐  ┌───────────────────────┐  │
│   │  Security  │  │  Agents   │  │    Data Vault         │  │
│   │           │  │           │  │                       │  │
│   │ Citadel   │  │ Opus 4.6  │  │ Encrypted capsules    │  │
│   │ UCAN      │  │ Trust-    │  │ Typed knowledge       │  │
│   │ E2E       │  │ aware     │  │ Semantic retrieval    │  │
│   │ Audit     │  │ reasoning │  │ Freshness tracking    │  │
│   └───────────┘  └───────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

Use cases beyond the family demo:
- **Enterprise teams**: Share project knowledge across departments with tiered access
- **Healthcare**: Care teams share patient routines with family members, revoke when care changes
- **Developer teams**: Share codebase knowledge, deployment procedures, API docs with agents
- **Legal/Finance**: Share sensitive documents with controlled access and full audit trail

---

## 2. Knowledge Sharing Lifecycle

### The Five Stages

```
┌──────────┐    ┌───────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  CREATE   │───▶│   SHARE   │───▶│ DISCOVER │───▶│  ACCESS  │───▶│  GOVERN  │
│           │    │           │    │          │    │          │    │          │
│ Author    │    │ Set tier  │    │ Agent    │    │ UCAN     │    │ Revoke   │
│ writes    │    │ Pick      │    │ finds    │    │ verified │    │ Rotate   │
│ capsule   │    │ networks  │    │ relevant │    │ decrypt  │    │ Audit    │
│ Encrypt   │    │ Issue     │    │ capsules │    │ respond  │    │ Expire   │
│           │    │ UCAN      │    │          │    │          │    │          │
└──────────┘    └───────────┘    └──────────┘    └──────────┘    └──────────┘
```

### Stage 1: CREATE

The knowledge owner authors a capsule:

```
Molly writes:
  Type: procedure
  Title: "Grandma Rose's Care Routine"
  Content: [full evening medication schedule...]
  Category: health

System actions:
  1. Content encrypted with Molly's vault master key → stored in SQLite
  2. Title + content embedded → vector stored in ChromaDB
  3. Capsule starts as tier="private" (safe default)
  4. No one else can see it yet
```

### Stage 2: SHARE

The owner explicitly decides who gets access:

```
Molly shares to "The Johnsons" network:
  1. Molly sets tier="network", selects network="The Johnsons"
  2. System re-encrypts capsule content with The Johnsons' network key
  3. CapsuleNetworkAccess record created (capsule_id ↔ network_id)
  4. UCAN capability token issued (see Section 3)
  5. Network members' agents can now discover this capsule

What triggers for network members:
  - Agent's accessible capsule set expands (on next query)
  - Optional: notification in the member's dashboard feed
  - Optional: agent proactively mentions "Molly shared new health info"
```

### Stage 3: DISCOVER

How does Peter know Molly shared something? Multiple discovery paths:

```
Path A: Query-driven discovery (primary)
  Peter asks his agent: "What does grandma need tonight?"
  → Agent resolves trust: Peter ↔ Molly, shared network "The Johnsons"
  → Semantic retrieval searches all accessible capsules
  → Finds "Grandma Rose's Care Routine" (high relevance)
  → Peter didn't need to know it existed — the agent found it

Path B: Network feed (UI)
  Peter opens dashboard → Network Activity feed shows:
  "Molly shared 'Grandma Rose's Care Routine' to The Johnsons — 2 hours ago"
  → Peter can browse, but can't see content until his agent mediates

Path C: Agent proactive notification
  Peter's agent, during a conversation: "By the way, Molly recently shared
  updated care instructions for Grandma Rose. Would you like me to go over them?"
  → Agent knows about new capsules in Peter's accessible networks

Path D: Vault browser (UI)
  Peter navigates to Networks → The Johnsons → Shared Knowledge
  → Sees list of capsule titles shared to this network (titles are not encrypted)
  → Can ask his agent about any of them
```

### Stage 4: ACCESS

When a member's agent accesses a shared capsule:

```
Peter's agent processes a query about grandma:

1. TRUST RESOLUTION
   Peter → Molly: connected ✓, shared network "The Johnsons" ✓
   Trust level: NETWORK

2. UCAN VERIFICATION
   Peter's agent presents its UCAN token for "The Johnsons" network
   Token claims: {iss: molly, aud: peter, scope: "read:network:johnsons", exp: ...}
   Verification: signature valid, not expired, not revoked ✓

3. CAPSULE DECRYPTION
   Peter's agent has The Johnsons' network key (encrypted for Peter's vault)
   Decrypt network key with Peter's vault master key
   Decrypt capsule content with network key
   Plaintext available to the agent in memory only

4. AGENT REASONING (Opus 4.6)
   Agent receives: decrypted capsule + trust context + question
   Agent reasons about what to share and how
   Agent responds with relevant information

5. AUDIT LOG
   Record: who accessed, what capsule, what trust level, what was shared
```

### Stage 5: GOVERN

Ongoing management of shared knowledge:

```
Revoke access:
  - Remove user from network → immediate loss of access
  - Change capsule tier from "network" to "private" → gone for everyone
  - Expire UCAN token → access denied on next query

Rotate keys:
  - Network key compromised → generate new key, re-encrypt all capsules
  - Re-issue encrypted network keys to all current members
  - Old keys invalidated

Audit:
  - Every access logged with: who, what, when, trust level, agent response
  - Network owner can review: "Who accessed grandma's care routine this week?"
  - Compliance report: "All access to health capsules in the last 30 days"

Expire:
  - Schedule capsules auto-archive after event date
  - Procedures flagged for review after 90 days
  - Stale capsules marked and surfaced to owner for refresh
```

---

## 3. UCAN Authorization Model

### Why UCAN?

Traditional auth (OAuth, sessions) has a fundamental problem for agent-to-agent sharing:

```
OAuth Problem:
  Every access check requires calling the authorization server
  If the server is down, no one can access anything
  Server is a single point of failure AND a surveillance bottleneck
  Can't delegate: Alice can't give Bob a scoped token for Charlie's data

UCAN Solution:
  Tokens are self-verifiable (no server roundtrip)
  Delegation is built-in (Alice → Bob → Charlie, each more restricted)
  Offline-capable (agents verify tokens locally)
  User-controlled (the user issues tokens, not a central authority)
```

### UCAN Structure

```
UCAN Token:
┌─────────────────────────────────────────────────────────┐
│ Header                                                   │
│   alg: "EdDSA"                                          │
│   typ: "JWT"                                            │
│   ucv: "0.10.0"                                         │
├─────────────────────────────────────────────────────────┤
│ Payload                                                  │
│   iss: "did:key:z6Mk..."     ← Issuer (who created it) │
│   aud: "did:key:z6Mn..."     ← Audience (who it's for) │
│   nbf: 1739350800            ← Not before (timestamp)  │
│   exp: 1739955600            ← Expires (timestamp)     │
│   nnc: "abc123"              ← Nonce (replay protect)  │
│   att: [                     ← Attenuations (capabilities)
│     {                                                    │
│       "with": "trustmesh://networks/johnsons",          │
│       "can": "capsule/read"                             │
│     }                                                    │
│   ]                                                      │
│   prf: ["bafy..."]           ← Proof chain (parent UCANs)
├─────────────────────────────────────────────────────────┤
│ Signature                                                │
│   [Ed25519 signature by issuer's private key]           │
└─────────────────────────────────────────────────────────┘
```

### UCAN Flows in TrustMesh

#### Flow 1: Network Membership Grant

```
Peter creates "The Johnsons" network and adds Molly:

1. Peter's DID: did:key:zPeter...
   Peter holds the root UCAN for "The Johnsons":
   {
     iss: "did:key:zPeter",    // Peter issued it (he's the owner)
     aud: "did:key:zPeter",    // To himself
     att: [{
       with: "trustmesh://networks/johnsons",
       can: "network/*"        // Full control
     }]
   }

2. Peter adds Molly → issues a delegated UCAN:
   {
     iss: "did:key:zPeter",    // Peter issued it
     aud: "did:key:zMolly",    // For Molly
     att: [{
       with: "trustmesh://networks/johnsons",
       can: "capsule/read"     // Can read capsules (not manage network)
     }, {
       with: "trustmesh://networks/johnsons",
       can: "capsule/write"    // Can share capsules TO this network
     }],
     exp: null,                // No expiry (permanent member)
     prf: ["<peter's root UCAN CID>"]  // Proof: Peter authorized this
   }

3. Molly's agent stores this UCAN in her vault
   Molly can now read/write capsules in The Johnsons network
```

#### Flow 2: Temporary Delegation

```
Molly is going on her work trip. Kyle needs temporary access to grandma's care:

1. Peter approves Kyle's connection request
   (Human decision — Kyle is now connected to Peter)

2. Molly issues a TEMPORARY, ATTENUATED UCAN to Kyle:
   {
     iss: "did:key:zMolly",    // Molly issued it (she has network access)
     aud: "did:key:zKyle",     // For Kyle
     att: [{
       with: "trustmesh://networks/johnsons",
       can: "capsule/read"     // Read only (not write)
     }, {
       with: "trustmesh://capsules/type",
       can: "read:procedure,contact"  // ONLY procedures and contacts
                                       // Not memories, not preferences
     }],
     exp: 1740182400,          // Expires Feb 21 (end of trip)
     prf: ["<molly's UCAN CID>"]  // Proof: Molly authorized this
   }

3. Kyle's agent stores this UCAN
   Kyle can now:
   ✓ Read Grandma Rose's Care Routine (procedure)
   ✓ Read Grandma Rose's Medical Contacts (contact)
   ✗ Cannot read Family Vacation Plans (memory — not in allowed types)
   ✗ Cannot read Bill's Allergies (preference — not in allowed types)
   ✗ Cannot write/modify anything
   ✗ Token expires Feb 21 automatically

4. After the trip:
   Token expires → Kyle's access gone
   No manual revocation needed
   Molly doesn't even have to remember to remove him
```

#### Flow 3: Sub-Delegation (Kyle Needs Help)

```
Kyle realizes he needs the home aide to help one evening:

1. Kyle tries to delegate his UCAN to the home aide:
   {
     iss: "did:key:zKyle",       // Kyle issued it
     aud: "did:key:zAide",       // For the aide
     att: [{
       with: "trustmesh://networks/johnsons",
       can: "capsule/read"       // Same or fewer permissions
     }, {
       with: "trustmesh://capsules/type",
       can: "read:procedure"     // ONLY procedures (Kyle removed contacts)
     }],
     exp: 1739610000,            // Expires in 4 hours (one evening)
     prf: ["<kyle's UCAN CID>"] // Proof chain: Peter → Molly → Kyle → Aide
   }

   But wait — can Kyle delegate?

2. CHECK: Does Kyle's UCAN allow delegation?
   Molly's token to Kyle did NOT include "delegate" capability
   → Kyle CANNOT sub-delegate
   → The aide request is DENIED

   This is intentional: Molly trusted Kyle, but didn't authorize
   Kyle to extend that trust to others.

3. If Molly HAD included delegation rights:
   att: [{
     with: "trustmesh://networks/johnsons",
     can: "capsule/read,delegate"  // Can read AND delegate
   }]
   → Kyle could sub-delegate, but only with EQUAL OR FEWER permissions
   → Aide gets procedure-read for 4 hours (more restricted than Kyle's token)
```

### UCAN Verification

```python
async def verify_ucan(token: str, required_capability: str, resource: str) -> bool:
    """
    Verify a UCAN token grants the required capability for a resource.

    Checks:
    1. Signature is valid (issuer's public key)
    2. Token is not expired
    3. Nonce hasn't been used (replay protection)
    4. Required capability is present in attenuations
    5. Resource matches the "with" field
    6. Proof chain is valid (each parent authorized the child)
    7. Token is not in the revocation list
    """
    # 1. Decode and verify signature
    header, payload, signature = decode_ucan(token)
    issuer_pubkey = resolve_did_key(payload["iss"])
    if not verify_signature(header + "." + payload, signature, issuer_pubkey):
        return False

    # 2. Check expiry
    if payload.get("exp") and time.time() > payload["exp"]:
        return False

    # 3. Check nonce (replay protection)
    if payload.get("nnc") and is_nonce_used(payload["nnc"]):
        return False
    mark_nonce_used(payload["nnc"])

    # 4. Check capability
    has_capability = any(
        att["can"] == required_capability or att["can"] == "*"
        for att in payload["att"]
        if matches_resource(att["with"], resource)
    )
    if not has_capability:
        return False

    # 5. Verify proof chain (recursive)
    for proof_cid in payload.get("prf", []):
        parent_ucan = await fetch_ucan(proof_cid)
        if not await verify_ucan(parent_ucan, required_capability, resource):
            return False

    # 6. Check revocation list
    if is_revoked(token_cid(token)):
        return False

    return True
```

---

## 4. Revocation

### The Revocation Problem

UCAN tokens are self-verifiable — which means the issuer can't "call them back." This is a feature for availability but a challenge for revocation. Three strategies:

### Strategy 1: Time-Based Expiry (Primary)

```
Default token lifetimes:
  - Permanent member: 30-day tokens, auto-renewed on agent startup
  - Temporary access: Custom expiry (hours to days)
  - One-time query: 5-minute token

Why this works:
  - Most revocation is just "wait for expiry"
  - Temporary delegation naturally expires
  - Worst case: attacker has access until token expires
  - Combine with short lifetimes for sensitive resources
```

### Strategy 2: Revocation List (Immediate)

```
For immediate revocation (e.g., employee fired, trust broken):

1. Issuer publishes revocation to a shared list:
   POST /api/ucan/revoke
   { token_cid: "bafy...", reason: "member_removed", revoked_at: "..." }

2. Agents check revocation list before honoring tokens:
   if is_revoked(token_cid):
       deny_access()

3. Revocation list is:
   - Append-only (can't un-revoke)
   - Distributed (cached by each agent)
   - Signed by the issuer (can't be forged)

Tradeoff:
  - Requires network access to check (not fully offline)
  - But only for revocation check, not for capability verification
  - Cache the list locally, sync periodically (every 5 min)
```

### Strategy 3: Key Rotation (Nuclear Option)

```
For network-wide revocation (key compromise, mass removal):

1. Network owner generates new network key
2. Re-encrypts all capsules with new key
3. Re-issues UCANs to remaining members with new key
4. Old key → invalid
5. Old UCANs → point to old key → fail verification

When to use:
  - Network key compromised
  - Major trust breach
  - Organizational restructuring
  - Annual key rotation (compliance)
```

---

## 5. Permissioning Model

### Capability Types

```
Network-level capabilities:
  network/manage    — Create/delete network, add/remove members
  network/read      — See network metadata and member list
  capsule/read      — Read capsules shared to this network
  capsule/write     — Share capsules TO this network
  capsule/delegate  — Issue attenuated tokens to others

Capsule-level capabilities:
  read:*            — Read any capsule type
  read:procedure    — Read only procedure capsules
  read:schedule     — Read only schedule capsules
  read:contact      — Read only contact capsules
  read:skill        — Read only skill capsules
  read:memory       — Read only memory capsules
  read:preference   — Read only preference capsules

Meta capabilities:
  delegate          — Can sub-delegate (with attenuation)
  audit/read        — Can read audit logs for this network
  member/invite     — Can invite connected users to network
```

### Permission Matrix (Default Roles)

| Capability | Owner | Member | Temporary Guest | External (Public) |
|-----------|-------|--------|-----------------|-------------------|
| network/manage | ✓ | ✗ | ✗ | ✗ |
| network/read | ✓ | ✓ | ✓ | ✗ |
| capsule/read | ✓ (all types) | ✓ (all types) | ✓ (restricted types) | ✗ |
| capsule/write | ✓ | ✓ | ✗ | ✗ |
| capsule/delegate | ✓ | Configurable | ✗ | ✗ |
| audit/read | ✓ | ✗ | ✗ | ✗ |
| member/invite | ✓ | Configurable | ✗ | ✗ |

### Grant Workflow

```
Scenario: Molly wants to share grandma's care routine with the family

Step 1: AUTHOR
  Molly creates capsule (tier=private initially)
  Content encrypted with Molly's vault key
  Only Molly's agent can see it

Step 2: CLASSIFY
  Molly sets capsule type: "procedure"
  Molly sets category: "health"
  System suggests: "Health procedures should be shared with care networks"

Step 3: SHARE
  Molly changes tier to "network"
  Molly selects "The Johnsons" network
  System:
    a) Re-encrypts content with The Johnsons network key
    b) Creates CapsuleNetworkAccess record
    c) Updates ChromaDB with network metadata filter
    d) Each member's UCAN already grants capsule/read for this network

Step 4: NOTIFY
  System creates a network activity event:
    { actor: "molly", action: "shared", capsule_title: "Grandma Rose's Care Routine",
      network: "The Johnsons", timestamp: "..." }
  Peter's dashboard shows the new share
  Jane and Bill's dashboards show the new share
  Agents can proactively mention it in conversations

Step 5: VERIFY
  Peter queries: "What does grandma need tonight?"
  → Trust resolution: network-level access ✓
  → UCAN verification: Peter's token for The Johnsons ✓
  → Capsule decrypted and returned
  → Peter gets the care routine ✓
```

### Revocation Workflow

```
Scenario: Molly removes Kyle from The Johnsons after her trip

Step 1: REVOKE MEMBERSHIP
  Molly → DELETE /api/networks/{johnsons_id}/members/{kyle_id}
  System:
    a) Removes NetworkMembership record
    b) Publishes UCAN revocation for Kyle's Johnsons token
    c) Deletes Kyle's encrypted copy of the network key
    d) Logs: { actor: "molly", action: "removed_member", target: "kyle",
              network: "The Johnsons", timestamp: "..." }

Step 2: IMMEDIATE EFFECT
  Kyle's next query attempt:
    → Trust resolution: Kyle ↔ Molly still connected
    → Shared networks: only "TechCorp PM Team" (Johnsons removed)
    → Trust level: NETWORK (but only for TechCorp capsules)
    → Grandma's care routine: INACCESSIBLE

Step 3: CLEANUP
  Kyle's agent:
    → UCAN token for The Johnsons is revoked
    → Network key for The Johnsons deleted from vault
    → Cannot decrypt any Johnsons-scoped capsule content
    → Even if Kyle cached the content, the key is gone

Step 4: AUDIT
  Network owner (Peter) can see:
    "Kyle was a member of The Johnsons from Feb 18 to Feb 22"
    "Kyle accessed 'Grandma Rose's Care Routine' 3 times"
    "Kyle accessed 'Grandma Rose's Medical Contacts' 1 time"
    "Kyle's access was revoked by Molly on Feb 22"
```

---

## 6. Internal Sharing Patterns

### Pattern 1: Broadcast to Network

```
Owner shares capsule to a network. All members can discover and access.

Use case: Molly shares grandma's care routine with the whole family.
All Johnsons can access. No per-member approval needed.
```

### Pattern 2: Targeted Share

```
Owner shares capsule to a specific member via UCAN delegation.
Not to a whole network — just one person.

Use case: Molly shares her private journal entry with Peter only.
She issues a UCAN directly to Peter (no network involved):
{
  iss: "did:key:zMolly",
  aud: "did:key:zPeter",
  att: [{ with: "trustmesh://capsules/<journal-id>", can: "capsule/read" }],
  exp: null  // Permanent (they're married)
}
Peter can read it. No one else in The Johnsons can.
```

### Pattern 3: Time-Boxed Access

```
Owner shares with automatic expiry. No manual revocation needed.

Use case: Kyle gets care routine access for Molly's trip.
UCAN expires Feb 21. Access disappears automatically.
```

### Pattern 4: Role-Based Sharing

```
Network defines roles with different capability sets.
New members inherit their role's capabilities.

Use case: TechCorp PM Team
  - Manager role: read + write + invite
  - Member role: read + write
  - Viewer role: read only
  - Contractor role: read specific capsule types only

Kyle joins as "Member" → gets read + write automatically
New contractor joins → gets read access to skills and schedules only
```

### Pattern 5: Cascading Revocation

```
Revoking a parent UCAN invalidates all child UCANs.

Use case: Peter is removed from The Johnsons (extreme scenario)
  - Peter's root UCAN for The Johnsons → revoked
  - Any UCANs Peter delegated from that root → also invalid
  - If Peter had delegated to a babysitter → babysitter's access gone too
```

---

## 7. How Internal Stakeholders Learn About Shared Knowledge

### Push Mechanisms (Active Notification)

```
1. Network Activity Feed
   Dashboard shows: "Molly shared 'Q4 Report Deadline' to TechCorp PM Team"
   Sorted by recency. Filter by network.

2. Agent Proactive Mentions
   During conversation, agent says:
   "I notice Peter recently shared updated electrical panel info.
    Would you like me to review it?"

3. Digest Notifications (future)
   Weekly email/notification: "3 new capsules shared to your networks this week"
   - "Grandma Rose's Care Routine" (health/procedure) by Molly
   - "Family Vacation Plans" (memory) by Peter
   - "Jane's Weekly Schedule" (schedule) by Jane

4. Webhook/API Events (for integrations)
   POST to configured webhook when capsule shared to your network
   Enables: Slack notifications, email alerts, CI/CD triggers
```

### Pull Mechanisms (Active Discovery)

```
1. Query-Driven Discovery (Primary)
   Ask your agent: "What do we know about grandma's care?"
   Agent searches across all your accessible networks
   Finds relevant capsules you may not have known about

2. Network Vault Browser
   Navigate to: My Networks → The Johnsons → Shared Knowledge
   See: list of capsule titles, types, authors, dates
   Click to ask agent about any capsule

3. Search Across Networks
   Search bar: "medication schedule"
   Returns capsules from ALL your networks matching the query
   Grouped by network, sorted by relevance

4. Agent-Mediated Browsing
   Ask agent: "What's been shared to The Johnsons recently?"
   Agent lists recent capsules with summaries
   You can drill into any of them
```

### Privacy of Discovery

```
Important: Discovery reveals TITLES, not CONTENT.

Capsule titles are not encrypted (needed for browsing/search).
But content IS encrypted with the network key.
Even if someone sees the title "Grandma Rose's Care Routine" in a list,
they cannot read the content without the network key.

For highly sensitive capsules, owners can use opaque titles:
  "Health Protocol A" instead of "Grandma Rose's Medication Schedule"
```

---

## 8. Implementation for Hackathon

### What We Build

```
Must-have (Day 2-3):
  ✓ Capsule sharing to networks (tier="network" + network selection)
  ✓ Trust resolution in query pipeline (connections → shared networks → tier)
  ✓ Network activity feed in UI (recent shares)
  ✓ Query audit log (who accessed what)
  ✓ Capsule access filtering (only accessible capsules in retrieval)

Nice-to-have (Day 3-4):
  ○ UCAN token generation for network membership
  ○ UCAN verification in query pipeline
  ○ Temporary access with expiry
  ○ Revocation list
  ○ Agent proactive notifications about new shares

Mention in demo/slides (future):
  ○ Sub-delegation (Kyle → aide)
  ○ Role-based network permissions
  ○ Key rotation
  ○ Webhook notifications
  ○ Full DID-based identity
```

### UCAN Integration Points

```python
# Where UCAN tokens fit in the current architecture:

# 1. Network membership → UCAN issued
@router.post("/api/networks/{network_id}/members")
async def add_member(network_id: str, user_id: str):
    # ... existing membership logic ...

    # NEW: Issue UCAN for this membership
    ucan = issue_ucan(
        issuer=network_owner_did,
        audience=new_member_did,
        capabilities=[
            {"with": f"trustmesh://networks/{network_id}", "can": "capsule/read"},
            {"with": f"trustmesh://networks/{network_id}", "can": "capsule/write"},
        ],
        expiry=None,  # Permanent member
        proof_chain=[owner_root_ucan],
    )
    store_ucan(user_id, network_id, ucan)

# 2. Query pipeline → UCAN verified
async def query_agent(from_user, to_user, question):
    trust_level, shared_networks = resolve_trust_level(from_user.id, to_user.id)

    # NEW: Verify UCAN for each shared network
    for network in shared_networks:
        ucan = get_ucan(from_user.id, network.id)
        if not verify_ucan(ucan, "capsule/read", f"trustmesh://networks/{network.id}"):
            shared_networks.remove(network)

    # Continue with verified networks only...

# 3. Revocation → UCAN invalidated
@router.delete("/api/networks/{network_id}/members/{user_id}")
async def remove_member(network_id: str, user_id: str):
    # ... existing removal logic ...

    # NEW: Revoke UCAN
    ucan = get_ucan(user_id, network_id)
    publish_revocation(ucan)
    delete_ucan(user_id, network_id)
```

---

## 9. Why This Matters for Positioning

### TrustMesh vs. Traditional Sharing

| Feature | Google Drive / SharePoint | Slack / Teams | TrustMesh |
|---------|--------------------------|---------------|-----------|
| Sharing unit | Files | Messages | **Typed knowledge capsules** |
| Access control | Folder-level ACLs | Channel membership | **Network-scoped UCAN tokens** |
| Discovery | Browse folders | Search messages | **Agent-mediated semantic search** |
| Intelligence | None | None | **Opus 4.6 reasons about what to share** |
| Encryption | Server-side | TLS only | **E2E (vault + network keys)** |
| Revocation | Manual permissions | Remove from channel | **UCAN expiry + revocation list** |
| Audit | Basic access logs | Message history | **Full trust decision audit trail** |
| Delegation | "Share" button | Forward message | **Attenuable UCAN tokens** |
| Freshness | File modified date | None | **Type-aware freshness with auto-archive** |
| Security scanning | DLP (enterprise) | None | **Citadel input + output scanning** |

### The Pitch

> "TrustMesh is the internal knowledge sharing layer for the agent era.
> Your AI agents hold your knowledge in encrypted vaults.
> You decide who gets access by creating networks and approving connections.
> UCAN tokens ensure delegation is safe — permissions can only shrink, never grow.
> Citadel guards every query. Every access is logged.
> It's not just sharing files — it's trust-aware knowledge sharing
> where AI agents reason about what to reveal and what to protect."
