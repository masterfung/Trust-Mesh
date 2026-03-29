# Knowledge Capsules: Storage, Retrieval, and Freshness

## Overview

Knowledge capsules are the core data unit in TrustMesh. Unlike simple key-value stores or flat document collections, capsules are **typed, tiered, time-aware, and semantically searchable**.

---

## 1. Capsule Types

| Type | What It Holds | Characteristics | Example |
|------|--------------|----------------|---------|
| **Memory** | Episodic knowledge — events, observations | Time-bound, decays naturally | "Jane left her wallet on the kitchen counter Tuesday" |
| **Skill** | How-to knowledge — expertise, techniques | Permanent, rarely changes | "House has 200A service, panel in garage, breakers 1-14 mapped" |
| **Procedure** | Step-by-step instructions | Critical accuracy, needs periodic verification | "Grandma's evening meds: Lisinopril 10mg + Amlodipine 5mg at 7pm" |
| **Schedule** | Time-based information | Auto-expires at event end, frequently updated | "Molly's Austin trip: Feb 18-21, AA1247 departs 6:15am" |
| **Preference** | Personal info, allergies, dietary restrictions | Permanent (especially medical), high importance | "Bill is lactose intolerant. EpiPen in kitchen drawer." |
| **Contact** | People, phone numbers, relationships | Needs periodic review (numbers change) | "Dr. Patel, cardiologist: (555) 345-6789, T/Th 9-4" |

### Type-Specific Agent Behavior

The capsule type guides how the agent presents information:

- **Memory**: Share naturally, conversationally. Qualify with "as of [date]" if old.
- **Skill**: Explain with appropriate detail level for the question.
- **Procedure**: Be **precise and complete** — these may involve health/safety. Never paraphrase medication dosages.
- **Schedule**: Include specific times, dates, flight numbers, confirmation codes.
- **Preference**: State clearly, especially allergies or medical info. Always mention EpiPen locations.
- **Contact**: Include office hours, specialties, when to call vs when not to.

---

## 2. Access Tiers

### Tier Definitions

| Tier | Who Can See | Use Case |
|------|------------|----------|
| **Public** | Anyone who queries | General bio, profession, public interests |
| **Network** | Members of specified networks | Family info, work data, shared knowledge |
| **Private** | Owner only | Personal journals, sensitive thoughts, unreleased plans |

### Network Scoping

A capsule with tier `network` is shared to specific networks. A single capsule can be shared to multiple networks:

```json
{
  "title": "Grandma Rose's Care Routine",
  "tier": "network",
  "network_ids": ["the-johnsons-id"]
}
```

```json
{
  "title": "Q4 Report Deadline",
  "tier": "network",
  "network_ids": ["techcorp-pm-id"]
}
```

A capsule shared to "The Johnsons" is visible to all Johnson family members but NOT to Kyle (who is only in "TechCorp PM Team").

---

## 3. Storage Architecture

### Dual Storage Model

```
┌──────────────────────────────────────────────────┐
│           Knowledge Layer (per user)              │
│                                                   │
│  SQLite (structured)     ChromaDB (semantic)      │
│  ┌─────────────────┐    ┌─────────────────────┐  │
│  │ Capsule metadata │    │ Capsule embeddings  │  │
│  │ - id, type, tier │───▶│ - vector (1536d)    │  │
│  │ - title          │    │ - capsule_id ref    │  │
│  │ - encrypted blob │    │ - metadata filters  │  │
│  │ - networks       │    │                     │  │
│  │ - freshness      │    │ Enables:            │  │
│  │ - expires_at     │    │ - Semantic search    │  │
│  │ - created_at     │    │ - Fuzzy matching     │  │
│  │ - updated_at     │    │ - Context ranking    │  │
│  └─────────────────┘    └─────────────────────┘  │
│                                                   │
│  AES-256-GCM encrypted at rest in SQLite          │
└──────────────────────────────────────────────────┘
```

### Why Two Stores?

- **SQLite**: Source of truth for metadata, access control, audit. Fast exact queries (get by ID, filter by tier/network).
- **ChromaDB**: Semantic retrieval. When someone asks "What does grandma need tonight?", vector similarity finds the care routine capsule even though the question doesn't match the title exactly.

### ChromaDB Benefits

- **In-process**: Runs alongside Python, no separate server
- **Metadata filtering**: Filter by capsule_id, tier, network before vector search
- **Automatic embedding**: Can use built-in or external embedding models
- **Zero infrastructure**: `pip install chromadb`, nothing else needed

---

## 4. Semantic Retrieval

### How It Works

When an agent receives a query, it doesn't dump all accessible capsules into the LLM context. Instead:

```python
async def retrieve_relevant_capsules(
    owner_id: str,
    question: str,
    accessible_capsule_ids: list[str],  # Pre-filtered by trust
    top_k: int = 5
) -> list[KnowledgeCapsule]:
    """Semantic search over ONLY accessible capsules."""

    # 1. Embed the question
    question_embedding = await embed_text(question)

    # 2. Query ChromaDB with trust-filtered IDs
    results = chroma_collection.query(
        query_embeddings=[question_embedding],
        where={"capsule_id": {"$in": accessible_capsule_ids}},
        n_results=top_k
    )

    # 3. Fetch full capsules from SQLite, decrypt content
    capsules = []
    for capsule_id in results["ids"][0]:
        capsule = await get_capsule(capsule_id)
        capsule.content = decrypt(capsule.content_encrypted, vault_key)
        capsules.append(capsule)

    return capsules  # Most relevant first
```

### Why This Matters

- **Context efficiency**: Sonnet 4.5 gets 3-5 relevant capsules, not 50 irrelevant ones
- **Better answers**: Agent reasons over focused context, not noise
- **Trust enforcement**: Only capsules passing the trust filter are searchable
- **Performance**: Vector search is O(log n), scales to thousands of capsules

### Embedding Strategy

```
Hackathon:
  - Model: Voyage AI (voyage-3) or sentence-transformers (all-MiniLM-L6-v2)
  - Input: title + " | " + decrypted_content
  - Dimension: 1536 (voyage) or 384 (MiniLM)
  - Chunking: Long capsules split at paragraph boundaries with 50-token overlap
  - Re-embed on capsule create/update

Production:
  - Fine-tuned embeddings for medical/technical domains
  - Hybrid search: vector similarity + BM25 keyword matching
  - Incremental re-embedding (only changed capsules)
```

---

## 5. Data Freshness & Rot Prevention

### The Problem

Knowledge capsules aren't static — they rot:
- Jane's wallet location is useless after she picks it up
- Molly's Austin trip ends Feb 21
- Grandma's medication dosages may change
- Bill's soccer schedule changes seasonally

If an agent serves stale knowledge, trust erodes.

### Freshness Model

Each capsule carries freshness metadata:

```python
class KnowledgeCapsule:
    # ... content fields ...
    freshness: str          # "permanent" | "temporary" | "recurring"
    expires_at: datetime    # Hard expiration (e.g., trip ends Feb 21)
    last_verified_at: datetime  # When owner last confirmed accuracy
    auto_archive_days: int  # Auto-archive after N days if unverified
    is_archived: bool       # Archived capsules excluded from queries
```

### Freshness Strategies by Type

| Type | Default Freshness | Rot Strategy |
|------|------------------|-------------|
| **Memory** | Temporary | Auto-archive after 30 days. Agent qualifies: "this may be outdated" |
| **Skill** | Permanent | No expiry. Skills don't rot (house wiring doesn't change) |
| **Procedure** | Permanent | Flag for review every 90 days (medical procedures must be verified) |
| **Schedule** | Temporary | Auto-expires at event end date. Past events archived |
| **Preference** | Permanent | Allergies/medical never expire. Lifestyle prefs flagged yearly |
| **Contact** | Permanent | Flag for review every 6 months (phone numbers can change) |

### Agent Behavior with Stale Data

```
Capsule past expires_at:
  → Agent does NOT use it
  → "I had that information but it may be outdated."

Capsule with old last_verified_at:
  → Agent uses it with qualification
  → "As of [date], [info]. You may want to verify this is still current."

Capsule is_archived:
  → Completely excluded from retrieval
  → Invisible to the agent
```

---

## 6. Capsule Lifecycle

### Creation

```
1. User creates capsule via UI or API
2. Content is encrypted with vault key (private) or network key (network)
3. Encrypted content stored in SQLite
4. Title + decrypted content embedded via embedding model
5. Embedding vector stored in ChromaDB with capsule_id reference
6. If tier="network", CapsuleNetworkAccess records created
```

### Update

```
1. User modifies content/tier/networks
2. Re-encrypt with appropriate key
3. Update SQLite record
4. Re-embed and update ChromaDB vector
5. Update network access records if tier changed
```

### Archive/Delete

```
Archive:
  1. Set is_archived = true
  2. Capsule excluded from all queries
  3. Embedding remains (can be un-archived)

Delete:
  1. Remove from SQLite
  2. Remove embedding from ChromaDB
  3. Remove CapsuleNetworkAccess records
  4. Irreversible
```

### Auto-Expiry

```python
async def check_capsule_freshness():
    """Periodic task to archive expired capsules."""
    now = datetime.now(timezone.utc)

    # Archive capsules past their expiration date
    expired = await get_capsules_where(expires_at__lt=now, is_archived=False)
    for capsule in expired:
        capsule.is_archived = True

    # Flag capsules needing verification review
    stale_procedures = await get_capsules_where(
        capsule_type="procedure",
        last_verified_at__lt=now - timedelta(days=90),
        is_archived=False
    )
    for capsule in stale_procedures:
        await notify_owner(capsule.owner_id, f"Please verify: {capsule.title}")
```

---

## 7. Demo Data Summary

### Peter's Capsules (4)

| Title | Type | Tier | Networks |
|-------|------|------|----------|
| House Electrical Panel Layout | Skill | Network | The Johnsons |
| What To Do If Power Goes Out | Procedure | Network | The Johnsons |
| Family Vacation Plans | Memory | Network | The Johnsons |
| Licensed Electrician | Skill | Public | — |

### Molly's Capsules (5)

| Title | Type | Tier | Networks |
|-------|------|------|----------|
| Grandma Rose's Care Routine | Procedure | Network | The Johnsons |
| Grandma Rose's Medical Contacts | Contact | Network | The Johnsons |
| Molly's Austin Work Trip | Schedule | Network | The Johnsons |
| Q4 Report Deadline | Schedule | Network | TechCorp PM Team |
| Project Manager | Skill | Public | — |
| Molly's Personal Journal | Preference | **Private** | — |

### Jane's Capsules (4)

| Title | Type | Tier | Networks |
|-------|------|------|----------|
| Jane's Weekly Schedule | Schedule | Network | The Johnsons |
| Jane's Lost Wallet | Memory | Network | The Johnsons |
| Jane's Public Bio | Preference | Public | — |
| Jane's Diary | Memory | **Private** | — |

### Bill's Capsules (4)

| Title | Type | Tier | Networks |
|-------|------|------|----------|
| Bill's Weekly Schedule | Schedule | Network | The Johnsons |
| Bill's Allergies and Medical | Preference | Network | The Johnsons |
| Bill's Bio | Skill | Public | — |
| Bill's Report Card | Memory | **Private** | — |

### Kyle's Capsules (2)

| Title | Type | Tier | Networks |
|-------|------|------|----------|
| API Migration Lead | Skill | Network | TechCorp PM Team |
| Software Engineer | Skill | Public | — |
