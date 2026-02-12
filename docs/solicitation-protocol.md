# Solicitation, Escalation, and Trust Safety

How TrustMesh handles discovery, abuse prevention, agent delegation, and human escalation.

---

## 1. The Solicitation Problem

TrustMesh agents are discoverable. Users have public profiles. This creates attack surfaces:

- **Mass-befriending**: A malicious user orders their agent to send connection requests to every discoverable user
- **Scraping**: Bots harvest public profile information at scale
- **Social engineering**: Attackers build fake trust networks to access network-tier capsules
- **Spam queries**: Even without connections, public-tier queries can overwhelm agents

### What Citadel Does and Doesn't Do

**Citadel IS**: A text guard layer. It scans query content for prompt injection (input) and data exfiltration (output). It operates on individual message content.

**Citadel IS NOT**: A rate limiter, abuse detector, or graph anomaly detector. It cannot detect "same user sent 500 connection requests today" because it only sees one message at a time.

We need **separate, application-level mechanisms** for solicitation abuse.

---

## 2. Defense Layers

### Layer 1: Connection Request Rate Limits (Application-Level)

```
Per-user limits:
- Max 10 connection requests per day
- Max 30 per week
- Max 50 pending (unreviewed) requests at any time
- Cooldown: 24 hours after 3 consecutive declines

Per-IP limits:
- Max 20 signups per day per IP
- Max 100 connection requests per day per IP
```

**Implementation**: Redis counters (or in-memory for hackathon) with sliding window rate limiting. These are NOT Citadel — they're FastAPI middleware.

```python
# Application-level rate limiting (NOT Citadel)
class ConnectionRateLimiter:
    async def check_can_send_request(self, user_id: str) -> tuple[bool, str]:
        daily_count = await self.get_daily_request_count(user_id)
        if daily_count >= 10:
            return False, "Daily connection request limit reached (10/day)"

        pending_count = await self.get_pending_request_count(user_id)
        if pending_count >= 50:
            return False, "Too many pending requests. Wait for responses."

        recent_declines = await self.get_recent_decline_count(user_id)
        if recent_declines >= 3:
            return False, "Cooldown active after multiple declined requests"

        return True, "ok"
```

### Layer 2: Query Rate Limits

```
Per-user query limits:
- Max 20 queries per hour to the same target
- Max 100 queries per day total
- Max 5 queries per minute (burst protection)

Public-tier queries (no connection):
- Max 5 per hour to the same target
- Max 20 per day total
```

Public-tier queries get stricter limits because the user hasn't been vetted through a connection approval.

### Layer 3: Web of Trust (Reputation)

New accounts start with a **trust score of 0**. Trust accrues through:

```
Trust Score Components:
- Account age: +1 per week (max 52)
- Accepted connections: +5 per accepted connection
- Network memberships: +10 per network
- Successful queries: +0.1 per allowed query
- Declined connections: -10 per decline
- Blocked by another user: -50 per block
- Citadel blocks: -25 per blocked query

Trust Thresholds:
- Score < 0: Account flagged for review, all outbound limited to 1/hour
- Score 0-10: New user, conservative limits apply
- Score 10-50: Established user, standard limits
- Score > 50: Trusted user, relaxed limits
```

This is graph-based: a user with many genuine, long-standing connections is more trustworthy than a new account with zero connections.

### Layer 4: Public Profile Protection

Public profiles are visible for discovery, but with progressive disclosure:

```
Level 0 (Unauthenticated): Display name only
Level 1 (Authenticated, no connection): Display name + bio
Level 2 (Connected): Display name + bio + public capsule summaries
Level 3 (Network member): Full access per network tier
Level 4 (Self): Everything including private

Anti-scraping:
- Search results paginated (max 20 per page)
- No bulk export endpoint
- Rate limit on /api/users search: 10 requests/minute
- CAPTCHA challenge after 50 searches per session
```

### Layer 5: Graph Anomaly Detection (Future / At Scale)

When you have Memgraph (or Neo4j) as the trust graph engine:

```cypher
// Detect mass-befriending: users who sent > 50 connection requests in 24h
MATCH (u:User)-[r:SENT_REQUEST]->(target:User)
WHERE r.created_at > datetime() - duration({hours: 24})
WITH u, count(r) as request_count
WHERE request_count > 50
RETURN u.id, request_count

// Detect Sybil clusters: groups of new accounts all connecting to each other
MATCH (u1:User)-[:CONNECTED_TO]-(u2:User)-[:CONNECTED_TO]-(u3:User)-[:CONNECTED_TO]-(u1)
WHERE u1.created_at > datetime() - duration({days: 7})
  AND u2.created_at > datetime() - duration({days: 7})
  AND u3.created_at > datetime() - duration({days: 7})
RETURN u1, u2, u3
```

---

## 3. Agent Escalation Protocol

When an agent receives a query and doesn't have the answer, what happens?

### The Tri-Path Model: RESPOND / SOLICIT / DELEGATE

```
Query arrives → Agent evaluates → One of three paths:

PATH 1: RESPOND (default)
  Agent has relevant capsules → answers directly
  This is the current implementation.

PATH 2: SOLICIT (ask the human)
  Agent lacks data → creates a pending request → notifies the human owner
  Human responds → agent delivers the answer

PATH 3: DELEGATE (ask another agent)
  Agent lacks data but knows who might have it →
  Agent forwards the query to another agent in the same network →
  That agent responds (or solicits their human)
```

### Path 2: SOLICIT — Human-in-the-Loop

**When it triggers**: The agent has no relevant capsules, OR the question requires information the agent isn't confident about.

**Flow**:

```
1. Bill asks Peter's agent: "What time is Jane's soccer game Saturday?"
2. Peter's agent checks capsules → no soccer schedule found
3. Agent creates a PendingRequest:
   {
     id: uuid,
     requester_id: bill.id,
     target_user_id: peter.id,
     question: "What time is Jane's soccer game Saturday?",
     status: "pending",        // → owner_notified → answered → delivered
     agent_note: "I don't have Jane's soccer schedule in my capsules.",
     created_at: now,
     expires_at: now + 24h,
     notification_sent: false
   }
4. Notification sent to Peter:
   - In-app: badge on dashboard + notification bell
   - Push: browser push notification (if enabled)
   - Future: SMS via Twilio, email
5. Peter sees: "Bill's agent asked yours: 'What time is Jane's soccer game Saturday?'"
6. Peter responds: "Game is at 9am at Riverside Park, field 3"
7. Agent delivers the answer to Bill's agent
8. Both agents log the exchange
```

**Data model addition**:

```python
class PendingRequest:
    id: uuid
    requester_id: str           # Who asked
    target_user_id: str         # Whose agent was asked
    question: str
    status: str                 # pending | owner_notified | answered | expired | cancelled
    agent_note: str             # Why the agent couldn't answer
    owner_response: str | None  # Human's answer
    trust_level: str            # Trust level at time of request
    notification_sent: bool
    created_at: datetime
    expires_at: datetime        # Auto-expire after 24h
    answered_at: datetime | None
```

**API endpoints**:

```
POST /api/pending-requests                    # Agent creates when it can't answer
GET  /api/users/{id}/pending-requests         # Human sees their pending requests
PUT  /api/pending-requests/{id}/respond       # Human provides an answer
GET  /api/users/{id}/pending-responses        # Requester sees delivered responses
```

### Path 3: DELEGATE — Agent-to-Agent Forwarding

**When it triggers**: The agent recognizes the question is about a domain that another network member likely knows about.

**Example**:
```
1. Bill asks Peter's agent: "What medication does grandma take at night?"
2. Peter's agent checks → no medication capsule found (Peter doesn't store this)
3. Agent recognizes this is a medical/care question → Molly is the primary caretaker
4. Agent creates a DelegatedQuery:
   {
     original_requester: bill.id,
     original_target: peter.id,
     delegated_to: molly.id,
     question: "What medication does grandma take at night?",
     reason: "Peter's agent doesn't have medication information.
              Delegating to Molly who manages grandma's care."
   }
5. Molly's agent receives the query with Bill's trust level
   (Bill is in The Johnsons → network access → sees care routine)
6. Molly's agent responds
7. Peter's agent relays the response to Bill
8. Full audit trail logged
```

**Critical rule**: Delegation NEVER elevates trust. If Bill has public-level access to Molly, the delegated query runs at public level, even if Peter has network-level access.

**Trust preservation**:
```python
def get_delegation_trust_level(original_requester_id, delegated_to_id):
    """Delegation uses the ORIGINAL requester's trust with the delegate."""
    return resolve_trust_level(original_requester_id, delegated_to_id)
    # NOT the intermediary's trust level
```

**Delegation limits**:
- Max 1 hop (Agent A → Agent B, no further chaining)
- Max 3 delegations per query (avoid infinite loops)
- Delegation only within shared networks
- Requester sees the delegation in the audit trail

---

## 4. Work Context Sharing

How TrustMesh extends to enterprise/work knowledge.

### Architecture: Shared Capsules, Individual Vaults

Work knowledge lives in individual vaults but is shared to work networks:

```
Kyle's Vault:
  ├── "API Migration Lead" (network: TechCorp PM Team)
  ├── "GraphQL Schema Notes" (network: TechCorp PM Team)
  └── "Job Search Notes" (PRIVATE — not shared to anyone)

Molly's Vault:
  ├── "Q4 Report Deadline" (network: TechCorp PM Team)
  ├── "Project Budget" (network: TechCorp PM Team)
  └── "Grandma Rose's Care" (network: The Johnsons — NOT visible to TechCorp)
```

Key principle: **Knowledge stays in the creator's vault**. Sharing means granting access, not copying data.

### Audit Trail

Every knowledge access is logged:

```python
class KnowledgeAccessLog:
    id: uuid
    capsule_id: str             # Which capsule was accessed
    capsule_owner_id: str       # Who owns it
    accessor_id: str            # Who accessed it
    access_type: str            # "query" | "delegation" | "direct"
    trust_level: str            # Trust level at access time
    network_id: str | None      # Which network enabled access
    question: str               # What was asked
    response_summary: str       # What was shared (truncated)
    timestamp: datetime
```

This gives us:
- **"Who accessed what"**: Full visibility into knowledge flows
- **"When and why"**: Timestamp + question that triggered the access
- **"Through which network"**: Which network membership enabled this access
- **Revocation audit**: When someone is removed from a network, we can show exactly what they had access to

### Work Memory Patterns

```
Individual Capsule:
  Owner creates → stores in their vault → shares to work network
  Only the owner can edit or delete
  Network members can query about it through the agent

Canonical Capsule (future):
  Multiple people contribute to a shared knowledge capsule
  Example: "TechCorp API Migration Status"
  Kyle adds technical status, Molly adds PM timeline, Sarah adds design review
  Each contribution is attributed and timestamped
  Conflicts are flagged for human resolution
```

### Transparency UI

```
Dashboard shows:
- "Your agent shared 3 capsules this week"
- "5 queries answered from TechCorp PM Team members"
- "Kyle accessed 'Q4 Report Deadline' via query yesterday"
- "No access to private capsules occurred"

Notification when accessed:
- "Kyle's agent queried about your Q4 Report — you can review what was shared"
- Owner can see the exact response their agent gave
```

---

## 5. Data Deduplication

### The Problem

Multiple family members store overlapping knowledge:
- Molly stores "Grandma's evening meds: Lisinopril 10mg + Amlodipine 5mg"
- Peter stores "Grandma takes Lisinopril 10mg at night"
- Partially overlapping, slightly different detail levels

### Detection

Use embedding similarity to detect near-duplicates:

```python
async def detect_duplicates(
    user_id: str,
    new_capsule_embedding: list[float],
    threshold: float = 0.85  # Cosine similarity threshold
) -> list[dict]:
    """Find capsules across the user's accessible scope that overlap with new content."""
    # Search within user's own vault first
    own_results = chroma_collection.query(
        query_embeddings=[new_capsule_embedding],
        where={"owner_id": user_id},
        n_results=5
    )

    duplicates = []
    for i, score in enumerate(own_results["distances"][0]):
        similarity = 1 - score  # ChromaDB returns distances
        if similarity >= threshold:
            duplicates.append({
                "capsule_id": own_results["ids"][0][i],
                "similarity": similarity,
                "suggestion": "merge" if similarity > 0.95 else "review"
            })

    return duplicates
```

### Resolution Strategies

```
Similarity > 0.95 (near-identical):
  → Suggest merge: "You already have this information in [capsule title]. Merge?"
  → Keep the more detailed/recent version
  → Archive the other

Similarity 0.85-0.95 (overlapping):
  → Flag for review: "This overlaps with [capsule title]. Review differences?"
  → Show a diff view in the UI
  → User decides: merge, keep both, or update one

Similarity < 0.85:
  → No action, they're different enough

Cross-user dedup (same network):
  → Agent-level synthesis: "Both Molly and Peter have grandma's medication info.
     Using Molly's version (more detailed, updated yesterday)."
  → Do NOT merge cross-user capsules automatically
  → Agent picks the most authoritative source at query time
```

### Agent-Level Synthesis

When queried, the agent may have access to multiple overlapping capsules (from the owner or network members' shared capsules). The agent already handles this through Opus 4.6 reasoning — it sees all relevant capsules and synthesizes the best answer.

The key improvement is **source attribution**: the agent should say "Based on Molly's care routine (updated Feb 10)..." rather than just presenting information without provenance.

---

## 6. Scale Architecture

### The Retrieval Pyramid

How to search 3T data points with AI context limits:

```
          ┌─────────────┐
          │  LLM Response│  ~2K tokens
          │  (Opus 4.6)  │
          ├──────────────┤
          │  Context     │  5 capsules → ~5K tokens
          │  Assembly    │  Re-rank, deduplicate, format
          ├──────────────┤
          │  Re-ranking  │  50 → 5 capsules
          │  (Cross-enc) │  LLM-based relevance scoring
          ├──────────────┤
          │  Vector      │  100K → 50 candidates
          │  Search      │  HNSW index, hybrid BM25+vector
          ├──────────────┤
          │  Trust       │  3T → 100K accessible capsules
          │  Filter      │  Network membership + tier checks
          ├──────────────┤
          │  Full        │  3T total capsules across all users
          │  Corpus      │  Encrypted, distributed across vaults
          └──────────────┘
```

### Stage Details

**Stage 1: Trust Filter (3T → 100K)**
- SQL query: get all capsule IDs where the requester has access
- This is already indexed (owner_id + tier + network_id)
- At scale: Memgraph resolves network membership, returns accessible vault IDs
- Latency: <10ms with proper indexing

**Stage 2: Vector Search (100K → 50)**
- ChromaDB (demo) → Pinecone/Qdrant/pgvector (production)
- HNSW index with metadata filtering (only search accessible IDs)
- Hybrid: BM25 keyword match + vector similarity (catches exact terms like drug names)
- Latency: ~20ms at 100K scale, ~50ms at 1M

**Stage 3: Re-ranking (50 → 5)**
- Cross-encoder model scores each of 50 candidates against the query
- Or: lightweight LLM call to select the 5 most relevant
- Factors: relevance, freshness, capsule type, source authority
- Latency: ~100ms

**Stage 4: Context Assembly (5 capsules → LLM)**
- Format the 5 capsules with metadata (type, freshness, source, last verified)
- Deduplicate overlapping content
- Fit within ~5K tokens of context
- Latency: <1ms

**Stage 5: LLM Response**
- Opus 4.6 reasons about what to share
- Latency: ~1-3s

### Vector Store Scaling Guide

```
Scale Tier     | Store          | Index Config
-------------- | -------------- | -----------------------------------
Demo (< 1K)    | ChromaDB       | In-memory, default HNSW
Small (< 100K) | ChromaDB       | Persistent, HNSW M=32, ef=200
Medium (< 1M)  | Qdrant/pgvec   | HNSW, product quantization (PQ)
Large (< 100M) | Pinecone       | Managed, S1 pods, metadata filtering
Massive (> 1B) | Pinecone/Qdrant| Sharded, binary quantization, tiered
```

---

## 7. Capsule Lifecycle Management at Scale

### The Problem

With 3,000+ capsules per user, management becomes overwhelming. You can't manually track what's fresh, what's stale, and what overlaps.

### Auto-Management Features

**Smart Archiving**:
```python
async def auto_archive_stale_capsules(user_id: str):
    """Archive capsules that are likely stale based on type and age."""
    rules = {
        "memory": {"max_age_days": 30, "unless_verified": True},
        "schedule": {"auto_expire": True},  # Uses expires_at field
        "contact": {"review_after_days": 180},
        "procedure": {"review_after_days": 90},
    }
    # Memories older than 30 days → auto-archive
    # Schedules past their end date → auto-archive
    # Contacts not verified in 6 months → flag for review
    # Procedures not verified in 3 months → flag for review
```

**AI-Assisted Organization**:
```
Agent analyzes your capsules and suggests:
- "You have 5 capsules about grandma's care. Want me to organize them into a Care folder?"
- "Your capsule 'Dr. Patel's number' is 8 months old. Still current?"
- "These 3 capsules overlap — want to merge into one?"
```

**Capsule Folders / Tags**:
```
My Vault (3,247 capsules)
├── Health & Care (45)
│   ├── Grandma Rose (12)
│   ├── Bill's Allergies (3)
│   └── Medical Contacts (8)
├── Home (23)
│   ├── Electrical (5)
│   └── Maintenance (8)
├── Work (156)
│   ├── Current Projects (34)
│   └── Archived Projects (89)
├── Family (67)
└── Auto-Archived (2,956)
```

**Smart Search** (already built — ChromaDB semantic search):
- Instead of browsing 3,000 capsules, just ask your agent
- "What do I know about the API migration?" → semantic search → top results
- The vault UI shows capsules, but the agent is the primary interface

---

## 8. Implementation Priority (Hackathon)

### Must Build (Day 2):
1. ~~Markdown rendering in chat~~ (DONE)
2. ~~"Ask your own agent" mode~~ (DONE)
3. Connection request rate limits (application-level, simple counter)
4. Query rate limits (same approach)
5. Documentation of the full architecture above

### Should Build (Day 3):
6. Pending request model + API for SOLICIT path
7. In-app notification for pending requests
8. Duplicate detection on capsule creation

### Document But Don't Build:
9. Memgraph integration for trust graph
10. Graph anomaly detection
11. Agent delegation (Path 3: DELEGATE)
12. Canonical capsules
13. Cross-encoder re-ranking
14. Voice AI integration

---

## 9. Tri-Store Architecture (Future)

```
┌─────────────────────────────────────────────────────────────┐
│                    TrustMesh Data Layer                      │
│                                                             │
│  SQLite/PostgreSQL     ChromaDB/Qdrant       Memgraph       │
│  ┌──────────────┐    ┌──────────────────┐  ┌────────────┐  │
│  │ Source of     │    │ Semantic search  │  │ Trust graph │  │
│  │ truth         │    │                  │  │             │  │
│  │ - Users       │    │ - Capsule embeds │  │ - Users     │  │
│  │ - Capsules    │───▶│ - Hybrid search  │  │ - Connects  │  │
│  │ - Networks    │    │ - Dedup detect   │  │ - Networks  │  │
│  │ - Auth        │    │                  │  │ - Trust     │  │
│  │ - Audit logs  │    │ At scale:        │  │   scores    │  │
│  │               │    │ - Pinecone/Qdrant│  │ - Anomaly   │  │
│  │ At scale:     │    │ - Sharded        │  │   detection │  │
│  │ - PostgreSQL  │    │ - PQ/BQ          │  │             │  │
│  │ - Partitioned │    │                  │  │ At scale:   │  │
│  │               │    │                  │  │ - Neo4j/    │  │
│  │               │    │                  │  │   Memgraph  │  │
│  └──────────────┘    └──────────────────┘  └────────────┘  │
│                                                             │
│  Each store serves a specific query pattern:                │
│  SQL: "Get capsule by ID, filter by tier"                   │
│  Vector: "Find capsules about grandma's meds"               │
│  Graph: "Who can access this capsule? Shortest trust path?" │
└─────────────────────────────────────────────────────────────┘
```
