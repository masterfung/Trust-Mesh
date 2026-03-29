# Design: Capsule Propagation & Downstream Impact Detection

## Problem Statement

When Peter changes his diet from vegetarian to pescatarian on his pod, that change affects:
- Molly's San Sebastian trip itinerary (restaurant choices)
- Rose's awareness of what Peter can eat at family dinners
- Any future agent query that references Peter's dietary constraints

Today, these downstream consumers only discover the change when they happen to re-query Peter's agent. There's no mechanism for:
1. Peter to **choose** whether others should be notified
2. The system to **detect** which existing capsules are now stale
3. Agents to **automatically re-trigger** research (e.g., TinyFish finding new restaurants)

---

## How Data Enters the System (and where propagation decisions happen)

Data enters through 5 paths. Each path needs to resolve propagation.

### Path 1: Onboarding (first-time pod setup)

User goes through `/[userId]/onboard/page.tsx`. They answer questions, the agent creates capsules.

**Current flow:**
```
User fills onboard form → agent runs → agent calls save_capsule for each answer
```

**With propagation:**
At the end of onboarding, the agent asks:
```
"You've shared some preferences with The Johnsons network.
If you change your diet or travel preferences later, should I
let the family know automatically?
  - Yes, notify them (recommended for family data)
  - No, keep changes private until they ask"
```

The agent sets `propagation` on each capsule based on the answer. The onboard page could also have a simple toggle: "Auto-notify my network when I update shared info."

This becomes a **user-level default** stored on the User model:
```python
# models.py — User
default_propagation: Mapped[str] = mapped_column(String(20), default="notify")
```

### Path 2: AI Chat (voice or text)

User talks to their agent in the chat page. Agent saves/updates capsules.

**Text example:**
```
Peter: "Actually I'm pescatarian now, I eat fish"
Agent: [calls save_capsule with updated diet, checks existing capsule,
        finds the travel preferences capsule, updates it]
```

**Voice example (future):**
```
Peter (voice): "Hey update my diet, I eat fish now"
→ Speech-to-text → same chat flow → agent updates capsule
```

**The agent's decision on propagation:**
The agent doesn't decide — it reads the `propagation` field already set on the capsule. If Peter's travel preferences capsule has `propagation=notify`, the update endpoint handles the rest. The agent doesn't need to know about propagation logic.

But if it's a NEW capsule (no existing one to update), the agent uses:
1. The user's `default_propagation` setting
2. The category default (see table below)
3. If unclear, asks the user

### Path 3: CLI (`trustmesh vault add` / `trustmesh vault update`)

```bash
# Explicit propagation flag
trustmesh vault add --title "My Diet" --content "Pescatarian" \
  --propagation notify

# Update — propagation mode is already on the capsule, no need to re-specify
# Unless you want to change it:
trustmesh vault update <id> --content "New content" --propagation broadcast

# New command: force-propagate right now (one-shot push)
trustmesh vault propagate <id>
# Sends notification to all network members immediately,
# regardless of the capsule's propagation setting
```

The `vault propagate` command is for the case where the capsule is `silent` but the user wants to manually push once: "Hey family, I updated this, go check."

### Path 4: UI Vault Editor

The capsule create/edit form in the UI gets a propagation selector.

Only shown when `visibility` is `internal` or `open` AND the capsule is shared to at least one network. No point showing it for private capsules.

```
When this capsule changes:
  ○ Don't notify anyone (silent)
  ● Notify network members (notify)      ← default for family/work
  ○ Notify with details of what changed (broadcast)
```

### Path 5: Returning User Updates

User comes back days later, updates an existing capsule. The `propagation` field is already set from when it was created. The update endpoint reads it and acts accordingly. No extra decision needed — the user already chose.

If they want to change the propagation mode itself:
- UI: edit the capsule, change the toggle
- CLI: `trustmesh vault update <id> --propagation silent`
- Agent: "Stop notifying people when I update my diet" → agent updates the propagation field

---

## Data Types That Should Auto-Propagate

Not just category-based. Specific data patterns that inherently affect others.

### Auto-propagation rules (applied at save time)

| Data Pattern | Detection | Default Propagation | Why |
|---|---|---|---|
| Allergies / dietary restrictions | title contains "allerg" "diet" "food" OR category=health + type=preference | `broadcast` | Safety — someone cooking for Peter needs to know immediately |
| Medications | title contains "med" "prescription" OR category=health + type=procedure | `broadcast` | Caregiver safety |
| Emergency contacts | type=contact + category=health | `broadcast` | Critical for Care Circle |
| Travel schedule / dates | type=schedule + (category=family OR category=work) | `notify` | Affects coordinated plans |
| Travel preferences | title contains "travel" "dining" "activity" | `notify` | Affects trip planning |
| Work deadlines | category=work + type=schedule | `notify` | Team coordination |
| Address / location changes | title contains "address" "location" "moved" | `notify` | Affects logistics |
| Private journal / thoughts | category=personal OR visibility=private | `silent` (forced) | NEVER propagate private thoughts |
| Financial info | category=financial | `silent` (forced) | Private by nature |

### Implementation: `_infer_propagation()` function

```python
def _infer_propagation(title: str, category: str, capsule_type: str,
                       visibility: str, user_default: str) -> str:
    """Infer propagation mode from capsule metadata."""
    # NEVER propagate private or financial data
    if visibility == "private" or category in ("personal", "financial"):
        return "silent"

    # Safety-critical: always broadcast
    title_lower = title.lower()
    if any(kw in title_lower for kw in ("allerg", "diet", "medication", "prescription",
                                         "emergency contact")):
        return "broadcast"

    # Travel/schedule: notify
    if any(kw in title_lower for kw in ("travel", "trip", "itinerary", "schedule",
                                         "deadline", "dining", "address")):
        return "notify"

    # Category defaults
    category_defaults = {
        "health": "broadcast",
        "family": "notify",
        "work": "notify",
        "home": "silent",
        "general": "silent",
    }
    cat_default = category_defaults.get(category, "silent")

    # User's own default as fallback
    return cat_default if cat_default != "silent" else user_default
```

This runs in Python (not Zig) because it needs the NLP-like keyword matching. Zig handles the storage and encryption; Python handles the intelligence.

---

## Zig vs Python Responsibilities

### What Zig owns (kernel layer)

| Component | Zig Responsibility |
|---|---|
| `knowledge_capsules` table | Schema includes `propagation VARCHAR(20) DEFAULT 'silent'` |
| Capsule CRUD handlers | Accept `propagation` field in JSON, store it, return it |
| FTS5 index | Index capsule content for staleness search |
| Transit engine | Encrypt/decrypt capsule content (unchanged) |
| Session/auth | Unchanged |

Zig does NOT:
- Run propagation logic (notification fan-out)
- Do keyword detection for auto-propagation
- Call federation endpoints
- Make AI decisions

### What Python owns (intelligence layer)

| Component | Python Responsibility |
|---|---|
| `_infer_propagation()` | Detect appropriate propagation from capsule metadata |
| Notification fan-out | After capsule update, send notifications to network members |
| Federation push | `POST /api/pod/notify` to peer pods for cross-pod propagation |
| Staleness detection | FTS5 search on recipient pod to find affected capsules |
| Agent hook | Generate timeline entry with hook_prompt for auto-retrigger |
| TinyFish re-trigger | Agent calls browse_web when research data is stale |

### What the AI Agent owns (reasoning layer)

| Responsibility | How |
|---|---|
| Clarify propagation on save | "Should I notify your family when you update this?" |
| Detect stale data on query | When answering, check if referenced capsules are flagged stale |
| Decide: re-query or use cached | If peer data is stale, re-query before answering |
| Decide: re-trigger TinyFish | If restaurant data was based on old diet, browse_web again |
| Compose update notification | "Peter changed his diet. Here's how it affects our trip plan." |

---

## The Re-trigger Flow (TinyFish / Research)

### Who runs TinyFish: Molly

Molly is the trip orchestrator. She owns the itinerary. Her agent is the one that:
1. Originally queried Peter + Rose
2. Originally ran TinyFish for restaurant research
3. Originally saved the itinerary

When Peter's diet changes, the re-trigger happens on Molly's pod, not Peter's.

### Trigger chain:

```
[Peter's Pod :9002]
  Peter updates diet capsule (propagation=notify)
  → capsule update endpoint detects propagation=notify
  → finds network members: Molly (ghost: remote:molly@localhost:9001)
  → POST http://localhost:9001/api/pod/notify
    { from_username: "peter",
      capsule_title: "Peter's Travel & Dining Preferences",
      capsule_category: "family",
      change_summary: "content updated" }

[Molly's Pod :9001]
  → receives /api/pod/notify
  → creates Notification for molly
  → runs staleness search: FTS5("peter travel dining preferences")
  → finds match: "San Sebastián Family Trip — 5-Day Itinerary"
    - mentions "Peter: vegetarian"
    - created before Peter's update timestamp
    - staleness_score = 5 (name mention + category + future date)
  → creates TimelineEntry:
    trigger_type: "event"
    trigger_event_type: "capsule.propagated.family"
    hook_prompt: "Peter updated his dining preferences. Your
      'San Sebastián Family Trip' itinerary references his old
      diet. Steps:
      1. query_peer peter — get updated preferences
      2. If diet changed, use browse_web to find restaurants
         matching the new diet in San Sebastián
      3. Update the itinerary capsule
      4. Save and share with The Johnsons"

[Molly's Agent — triggered by Timeline]
  → runs hook_prompt
  → query_peer(peter) → "Pescatarian, loves sushi, ceviche..."
  → browse_web(michelin guide) → finds seafood restaurants via TinyFish
  → updates itinerary capsule
  → saves with propagation=notify
  → Peter + Rose get notified: "Molly updated the trip plan"
```

### Cost gate

TinyFish calls cost API credits. Before auto-triggering:

```python
# In the timeline hook evaluation:
if hook_requires_web_research(hook_prompt):
    # Check user's auto-research setting
    if user.auto_research_enabled:
        # Run it
        pass
    else:
        # Create notification instead of auto-running
        create_notification(
            "Peter changed his diet. Your trip plan may need updating. "
            "[Run auto-update] or [Review manually]"
        )
```

Default: ask before spending credits. Power users can enable auto-research.

---

## Test Plan

### Unit Tests (pytest)

```
tests/test_propagation.py

test_capsule_create_default_propagation
  → Create capsule with category=family, no explicit propagation
  → Assert propagation == "notify" (category default)

test_capsule_create_explicit_propagation
  → Create capsule with --propagation=silent
  → Assert propagation == "silent" (overrides category default)

test_capsule_create_private_forces_silent
  → Create capsule with visibility=private, propagation=broadcast
  → Assert propagation == "silent" (private always silent)

test_infer_propagation_allergy
  → title="Peter's Allergies", category=health
  → Assert inferred == "broadcast"

test_infer_propagation_travel
  → title="Travel Preferences", category=family
  → Assert inferred == "notify"

test_infer_propagation_journal
  → title="Private Journal", category=personal
  → Assert inferred == "silent"

test_update_capsule_notify_sends_notifications
  → Create capsule (propagation=notify) shared to network with 2 members
  → Update capsule content
  → Assert 2 Notification records created
  → Assert notification body contains capsule title

test_update_capsule_silent_no_notifications
  → Create capsule (propagation=silent) shared to network
  → Update capsule
  → Assert 0 Notification records created

test_update_capsule_broadcast_includes_changes
  → Create capsule (propagation=broadcast)
  → Update content
  → Assert notification body contains "Changed: content"
```

### Integration Tests (multi-pod)

```
tests/test_propagation_federation.py
(requires running pods — like test_multi_pod.py)

test_cross_pod_propagation_notify
  → Peter (:9002) updates capsule with propagation=notify
  → Assert POST /api/pod/notify was sent to Molly's pod (:9001)
  → Assert Molly has a Notification record

test_cross_pod_staleness_detection
  → Molly has itinerary capsule mentioning "Peter: vegetarian"
  → Peter updates diet
  → Propagation notification arrives on Molly's pod
  → Assert: itinerary is flagged stale
  → Assert: timeline entry created with hook_prompt

test_cross_pod_retrigger
  → Full chain: Peter updates → Molly notified → agent re-queries →
    gets pescatarian → updates itinerary
  → Assert: updated itinerary contains "pescatarian"
```

### CLI Tests

```
test_cli_vault_add_propagation
  → `trustmesh vault add --propagation notify ...`
  → `trustmesh vault get <id>`
  → Assert output shows propagation mode

test_cli_vault_update_propagation
  → `trustmesh vault update <id> --propagation broadcast`
  → Assert field changed

test_cli_vault_propagate_command
  → `trustmesh vault propagate <id>`
  → Assert notifications sent to network members
```

### Zig Tests

```
kernel/src/tests/test_capsules.zig

test_capsule_create_with_propagation
  → POST /api/capsules with propagation=notify
  → Assert stored in DB
  → GET /api/capsules/<id>
  → Assert propagation=notify in response JSON

test_capsule_update_preserves_propagation
  → Create with propagation=broadcast
  → Update content only
  → Assert propagation still broadcast

test_capsule_propagation_default
  → Create without propagation field
  → Assert defaults to "silent"
```

### E2E / Playwright Tests

```
e2e/06-propagation.spec.ts

test_propagation_toggle_visible_for_shared_capsules
  → Login, create capsule with visibility=internal
  → Assert propagation toggle is visible in editor

test_propagation_toggle_hidden_for_private
  → Create capsule with visibility=private
  → Assert propagation toggle NOT shown

test_notification_appears_on_update
  → Pod A: create shared capsule with propagation=notify
  → Pod A: update capsule
  → Pod B: check inbox
  → Assert notification appears
```

---

## Demo Narrative

**Today's demo (what we record):**
1. Show data silos problem (diagram)
2. Molly queries Peter + Rose via federation
3. Peter updates diet in CLI
4. Molly re-queries → sees pescatarian
5. Narrate: "Today this re-query is manual. With propagation, it's automatic."

**What's next (pitch slide):**
"When Peter changes his diet, the system:
- Notifies Molly automatically
- Detects the itinerary is stale
- Re-triggers TinyFish for new restaurants
- Updates the plan — zero manual coordination"

This is the Phase 2-5 roadmap. The demo proves the foundation works. Propagation is the unlock.

---

## Scalability & Performance Deep Dive

This section answers the Open Questions from the original design and provides concrete analysis of propagation behavior at scale. Every claim is grounded in the actual TrustMesh architecture: Zig kernel (SQLite FTS5, transit engine, session management), Python intelligence layer (FastAPI, httpx federation, LLM agents), and the pod-per-user federation model.

---

### 1. Big-O Analysis of Propagation Fan-out

#### The Model

When Peter updates 1 capsule on his pod, the system must:

1. **Membership resolution**: Find all networks this capsule is shared with, then all members of those networks.
2. **Pod deduplication**: Group members by their home pod (ghost users carry `remote_pod_url`).
3. **Federation HTTP calls**: Send one `POST /api/pod/notify` per distinct remote pod.
4. **Staleness search**: Each receiving pod runs FTS5 to find locally-affected capsules.
5. **Timeline entry creation**: Each receiving pod creates a `TimelineEntry` with a `hook_prompt` for agent re-trigger.

#### Variables

| Symbol | Meaning | Typical | Stress |
|--------|---------|---------|--------|
| C | Capsules updated in a batch | 1 | 10,000 |
| N | Networks the capsule is shared with | 2 | 20 |
| M | Total unique members across all N networks | 8 | 1,000 |
| P | Distinct remote pods (after dedup) | 4 | 200 |
| K | Capsules on each receiving pod (for FTS5) | 50 | 10,000 |

#### Step-by-step complexity for 1 capsule update

| Step | Operation | Complexity | Bound by |
|------|-----------|------------|----------|
| 1. Find networks | `SELECT network_id FROM capsule_network_access WHERE capsule_id = ?` | O(N) | DB index on `capsule_id` |
| 2. Find members | `SELECT user_id FROM network_memberships WHERE network_id IN (...)` | O(M) | DB index on `network_id` |
| 3. Resolve pods | Group members by `remote_pod_url` (hash map) | O(M) | In-memory |
| 4. Federation calls | `POST /api/pod/notify` to each distinct pod | O(P) | Network I/O |
| 5. Staleness search (per pod) | FTS5 MATCH over K capsules | O(K log K) | SQLite BM25 |
| 6. Timeline entry (per pod) | INSERT into timeline | O(1) per pod | DB write |

**Total for 1 capsule**: O(N + M + P * K log K)

The dominant cost is step 4+5: P federation calls, each triggering an FTS5 search over K capsules. Steps 1-3 are local SQL queries (sub-millisecond on SQLite with indexes).

#### Concrete analysis: 10 capsules, 100 members

```
C = 10 capsules (Peter edits diet, travel, allergies, etc.)
N = 3 networks (The Johnsons, Care Circle, Work Team)
M = 100 unique members (some overlap across networks)
P = 16 pods (multi-pod demo setup)
K = 50 capsules per receiving pod (typical)

Without batching:
  Membership queries:  10 * (3 + 100) = 1,030 DB reads
  Federation calls:    10 * 16 = 160 HTTP POSTs
  FTS5 searches:       160 * 50 = 8,000 BM25 comparisons
  Timeline entries:    160 INSERTs

  Wall-clock time (estimated):
    Membership:  1,030 * 0.1ms = ~103ms (SQLite indexed)
    Federation:  160 * 15ms = ~2,400ms (sequential)
                 160 * 15ms / 10 = ~240ms (10x parallel)
    FTS5:        8,000 * 0.01ms = ~80ms (in-process Zig)
    Timeline:    160 * 0.1ms = ~16ms

  Total (parallel federation): ~440ms
  Total (sequential):          ~2,600ms
```

#### Concrete analysis: 10,000 capsules, 1,000 connections (stress case)

```
C = 10,000 capsules (bulk import or migration)
N = 20 networks
M = 1,000 unique members
P = 200 pods
K = 10,000 capsules per receiving pod

Without batching:
  Membership queries:  10,000 * (20 + 1,000) = 10,200,000 DB reads  ** PROBLEM **
  Federation calls:    10,000 * 200 = 2,000,000 HTTP POSTs           ** CATASTROPHIC **
  FTS5 searches:       2,000,000 * log(10,000) = ~26M comparisons
  Timeline entries:    2,000,000 INSERTs

  This is clearly untenable. Batching is mandatory.

With batching (C capsules -> 1 batch per pod):
  Membership queries:  1 bulk query (all 10,000 capsule IDs) = O(C + M)
  Federation calls:    200 HTTP POSTs (1 per pod, payload lists all capsule titles)
  FTS5 searches:       200 * O(K log K) = 200 * ~130 = ~26,000 comparisons
  Timeline entries:    200 INSERTs (1 per pod, with aggregated hook_prompt)

  Total (parallel federation, 20 workers): 200/20 * 15ms = ~150ms
  Total with membership + FTS5: ~300ms
```

**Verdict**: Batching reduces the stress case from 2M federation calls to 200. This is the single most important optimization.

#### Twitter-scale comparison: fan-out-on-write vs fan-out-on-read

Twitter faced this exact problem with tweet delivery to followers:

| Strategy | Twitter | TrustMesh | Applies? |
|----------|---------|-----------|----------|
| **Fan-out-on-write** | When @user tweets, pre-compute and write to every follower's timeline | When Peter updates a capsule, push notification to every network member's pod | Yes (current design) |
| **Fan-out-on-read** | When a user opens their timeline, query all followed users for recent tweets | When Molly queries Peter, check if any of his capsules changed since last query | Partial (already exists via `query_peer`) |
| **Hybrid** | Fan-out-on-write for normal users, fan-out-on-read for celebrities (>10M followers) | Fan-out-on-write for `broadcast`, fan-out-on-read for `notify` | Recommended |

**TrustMesh's advantage over Twitter**: Our "follower" count is bounded by trust network size. A personal AI agent's network is 5-50 people, not millions. Fan-out-on-write is viable because M is small. The stress case (1,000 members) is Twitter's easy case.

**Recommended hybrid**:
- `broadcast`: Fan-out-on-write. Push immediately. Safety-critical data (allergies, medications) must not wait.
- `notify`: Fan-out-on-write with batching and debounce (see Section 2). The receiving pod gets a "Peter updated some capsules" notification, not the full content.
- `silent`: Fan-out-on-read only. The next `query_peer` call will see the updated data. Zero push overhead.

---

### 2. Batching Strategy

#### The Problem

Peter opens his vault and updates 5 capsules in 30 seconds:
1. Diet preferences (t=0s)
2. Travel dining preferences (t=8s)
3. Allergy information (t=15s)
4. San Sebastian restaurant notes (t=22s)
5. Family dinner preferences (t=28s)

Without batching, the system sends 5 separate `POST /api/pod/notify` calls to each of Molly's, Rose's, and every other network member's pod. Molly's agent gets 5 separate staleness searches and potentially 5 separate TinyFish re-triggers.

#### Design: Pod-level Debounce with Priority Override

```
Debounce window: 5 seconds (configurable via TRUSTMESH_PROPAGATION_DEBOUNCE_MS)
Priority override: broadcast-level capsules bypass debounce (allergies, medications)
```

The debounce happens on the **source pod** (Peter's), not the receiving pod. This is critical: the source pod knows the update rate and can aggregate.

```
Timeline of events:

t=0s   Peter updates diet         → debounce timer starts (5s window)
t=5s   Timer fires                → BATCH: [diet] → send to all pods
t=8s   Peter updates dining       → debounce timer starts
t=13s  Timer fires                → BATCH: [dining] → send to all pods
t=15s  Peter updates allergies    → propagation=broadcast → IMMEDIATE send (bypasses debounce)
t=15s  Also starts debounce timer for non-broadcast
t=22s  Peter updates restaurants  → added to debounce buffer
t=28s  Peter updates dinner prefs → added to debounce buffer
t=33s  Timer fires                → BATCH: [restaurants, dinner prefs] → send to all pods

Result: 4 federation calls per pod instead of 5
        The allergy update was instant (safety-critical)
        The last two updates were batched together
```

#### Implementation: Zig-side debounce buffer vs Python asyncio

| Aspect | Zig debounce | Python asyncio debounce |
|--------|-------------|------------------------|
| Timer precision | Zig's event loop (io_uring / kqueue) — microsecond precision | `asyncio.call_later()` — millisecond precision |
| Buffer storage | Fixed-size ring buffer in Zig heap (no GC) | Python list (GC-managed) |
| Capsule ID tracking | `[64]u8` fixed arrays, zero-alloc | Python strings (heap allocated) |
| Federation calls | Must cross FFI boundary to Python (httpx) | Native Python httpx |
| Complexity | Moderate (Zig timers + ctypes callback) | Low (asyncio is designed for this) |

**Recommendation: Python asyncio debounce.** The debounce buffer is not on the hot path (it fires once every 5 seconds, not per-request). The federation calls are Python httpx anyway, so crossing FFI back and forth adds complexity for no measurable gain.

#### Code sketch: `PropagationBatcher`

```python
# src/propagation.py

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    CapsuleNetworkAccess, KnowledgeCapsule,
    NetworkMembership, User,
)
from src.federation import POD_URL, FEDERATION_TIMEOUT

log = logging.getLogger(__name__)

DEBOUNCE_SECONDS = float(os.getenv("TRUSTMESH_PROPAGATION_DEBOUNCE_MS", "5000")) / 1000


@dataclass
class PendingPropagation:
    capsule_id: str
    capsule_title: str
    capsule_category: str
    propagation: str  # "notify" | "broadcast"
    change_summary: str
    owner_username: str


@dataclass
class PropagationBatcher:
    """Debounces capsule update notifications per destination pod.

    Usage:
        batcher = PropagationBatcher()
        await batcher.enqueue(db, capsule, change_summary)
        # ... on shutdown:
        await batcher.flush_all()
    """
    _buffers: dict[str, list[PendingPropagation]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _timers: dict[str, asyncio.TimerHandle] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def enqueue(
        self, db: AsyncSession, capsule: KnowledgeCapsule,
        change_summary: str, owner_username: str,
    ) -> None:
        """Enqueue a capsule update for batched propagation.

        broadcast-level capsules bypass debounce and send immediately.
        """
        if capsule.propagation == "silent":
            return

        pending = PendingPropagation(
            capsule_id=capsule.id,
            capsule_title=capsule.title,
            capsule_category=capsule.category,
            propagation=capsule.propagation,
            change_summary=change_summary,
            owner_username=owner_username,
        )

        # Resolve destination pods (cached for debounce window)
        pod_urls = await self._resolve_destination_pods(db, capsule)

        if capsule.propagation == "broadcast":
            # Safety-critical: bypass debounce, send immediately
            await self._send_batch(pod_urls, [pending])
            return

        # Add to debounce buffer per pod
        async with self._lock:
            for pod_url in pod_urls:
                self._buffers[pod_url].append(pending)
                # Reset timer for this pod
                if pod_url in self._timers:
                    self._timers[pod_url].cancel()
                loop = asyncio.get_event_loop()
                self._timers[pod_url] = loop.call_later(
                    DEBOUNCE_SECONDS,
                    lambda url=pod_url: asyncio.ensure_future(
                        self._flush_pod(url)
                    ),
                )

    async def _flush_pod(self, pod_url: str) -> None:
        """Flush the debounce buffer for a single pod."""
        async with self._lock:
            batch = self._buffers.pop(pod_url, [])
            self._timers.pop(pod_url, None)
        if batch:
            await self._send_batch([pod_url], batch)

    async def _send_batch(
        self, pod_urls: list[str], batch: list[PendingPropagation],
    ) -> None:
        """Send a batched notification to multiple pods in parallel."""
        payload = {
            "from_pod": POD_URL,
            "capsules": [
                {
                    "capsule_id": p.capsule_id,
                    "title": p.capsule_title,
                    "category": p.capsule_category,
                    "change_summary": p.change_summary,
                }
                for p in batch
            ],
            "owner_username": batch[0].owner_username,
            "propagation": max(p.propagation for p in batch),  # highest level wins
        }

        async def _send_one(url: str):
            try:
                async with httpx.AsyncClient(timeout=FEDERATION_TIMEOUT) as client:
                    await client.post(
                        f"{url.rstrip('/')}/api/pod/notify",
                        json=payload,
                    )
            except Exception as e:
                log.warning("propagation: failed to notify %s: %s", url, e)

        await asyncio.gather(*[_send_one(url) for url in pod_urls])

    async def _resolve_destination_pods(
        self, db: AsyncSession, capsule: KnowledgeCapsule,
    ) -> list[str]:
        """Find all distinct remote pod URLs that need notification."""
        # Step 1: networks this capsule is shared with
        result = await db.execute(
            select(CapsuleNetworkAccess.network_id)
            .where(CapsuleNetworkAccess.capsule_id == capsule.id)
        )
        network_ids = [r[0] for r in result.all()]
        if not network_ids:
            return []

        # Step 2: members of those networks who are remote (ghost users)
        result = await db.execute(
            select(User.remote_pod_url)
            .join(NetworkMembership, NetworkMembership.user_id == User.id)
            .where(
                NetworkMembership.network_id.in_(network_ids),
                User.is_remote == True,       # noqa: E712
                User.remote_pod_url != None,  # noqa: E711
                User.id != capsule.owner_id,  # don't notify self
            )
            .distinct()
        )
        return [r[0] for r in result.all() if r[0]]

    async def flush_all(self) -> None:
        """Flush all pending buffers (called on shutdown)."""
        async with self._lock:
            urls = list(self._buffers.keys())
        for url in urls:
            await self._flush_pod(url)
```

#### Trade-off: Latency vs Notification Spam

| Debounce window | Notification count (5 capsules / 30s) | Latency (worst case) | Use case |
|-----------------|---------------------------------------|----------------------|----------|
| 0s (no debounce) | 5 per pod | 0ms | Safety-critical only |
| 2s | 4-5 per pod | 2s | Low-latency preference |
| 5s (recommended) | 2-3 per pod | 5s | Good balance |
| 15s | 1-2 per pod | 15s | Batch-heavy users |
| 60s | 1 per pod | 60s | Background sync only |

**Recommendation**: 5 second default. `broadcast` bypasses debounce. Users never set this directly; it is a pod-level configuration for operators.

---

### 3. Cascade Depth & Loop Prevention

#### The Scenario

```
1. Molly updates her San Sebastian itinerary (propagation=notify)
2. → Rose's pod receives notification
3. → Rose's agent detects her "Family Dinner Menu" capsule references Molly's itinerary
4. → Rose's agent auto-updates the dinner menu
5. → Rose's dinner menu has propagation=notify
6. → Peter's pod receives notification
7. → Peter's agent detects his "Dietary Preferences" were referenced
8. → Peter's agent updates... wait, this triggers Molly again?
```

This is the classic distributed cycle problem. In graph theory: Molly -> Rose -> Peter -> Molly is a cycle of length 3.

#### Option A: `propagation_depth` counter

```python
# In the /api/pod/notify payload:
{
    "capsules": [...],
    "propagation_depth": 0,  # incremented by each hop
}

# Receiving pod:
if payload.propagation_depth >= MAX_PROPAGATION_DEPTH:
    # Create notification but do NOT trigger agent auto-update
    create_notification(user, "Capsule updated (cascade limit reached)")
    return

# If agent auto-updates a capsule as a result:
new_depth = payload.propagation_depth + 1
await batcher.enqueue(db, updated_capsule, change_summary,
                      propagation_depth=new_depth)
```

| Depth limit | Behavior | Risk |
|-------------|----------|------|
| 0 | Only direct updates propagate | No cascades, some staleness |
| 1 | One hop allowed (Molly -> Rose, but Rose -> Peter stops) | Safe, covers 95% of cases |
| 2 | Two hops (Molly -> Rose -> Peter, but Peter -> Molly stops) | Higher risk of amplification |
| Unlimited | Full cascade until no more changes | Guaranteed infinite loops |

#### Option B: `propagation_origin_id` (origin tracking)

```python
# In the /api/pod/notify payload:
{
    "capsules": [...],
    "propagation_origin": {
        "capsule_id": "original-capsule-uuid",
        "pod_url": "http://localhost:9001",
        "timestamp": "2026-03-28T10:00:00Z"
    }
}

# Receiving pod:
# Before triggering agent auto-update, check:
if origin.capsule_id in recently_processed_origins:
    # Already seen this origin — cycle detected, stop
    return
recently_processed_origins.add(origin.capsule_id, ttl=300)  # 5 min TTL
```

#### Comparison

| Aspect | Depth counter | Origin tracking |
|--------|--------------|-----------------|
| Implementation complexity | Low (single integer) | Medium (origin cache with TTL) |
| Storage overhead | 0 (in payload only) | O(recent_origins) per pod |
| Handles complex cycles | Yes (any depth) | Yes (any topology) |
| False positives | Depth=1 may block legitimate 2-hop chains | Origin cache TTL may expire, allowing re-trigger |
| Debuggability | Easy (just log the depth) | Harder (need to inspect origin cache) |

#### Concrete Recommendation: Depth = 1, with origin tracking as a safety net

```python
MAX_PROPAGATION_DEPTH = 1  # Direct updates only, no cascading

# In the notify payload:
{
    "capsules": [...],
    "propagation_depth": 0,
    "propagation_origin_id": "uuid-of-originally-edited-capsule",
}

# Receiving pod logic:
def should_propagate_cascade(depth: int, origin_id: str) -> bool:
    if depth >= MAX_PROPAGATION_DEPTH:
        return False  # Hard stop
    if origin_id in _seen_origins:
        return False  # Cycle detected
    _seen_origins[origin_id] = time.time()  # TTL cleanup via periodic sweep
    return True
```

**Rationale**: Depth=1 is sufficient because TrustMesh's data model is owner-centric. Peter owns his diet capsule. When it changes, Molly gets notified and her agent updates her itinerary. But Molly's itinerary update should NOT cascade back to Peter automatically. Peter was the original trigger; he already knows his diet changed. The notification to Peter ("Molly updated the trip plan") is informational only and should not trigger Peter's agent.

The origin tracking is a safety net for edge cases where depth counting alone might not catch complex topologies (e.g., A -> B -> C -> A where C is not aware of A's original change).

---

### 4. Opt-out & Subscription Model

#### Two approaches

**Option A: Per-capsule subscription**

```sql
CREATE TABLE capsule_subscriptions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    capsule_id  TEXT NOT NULL REFERENCES knowledge_capsules(id),
    muted       BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, capsule_id)
);
```

**Option B: Per-network mute**

```sql
CREATE TABLE network_subscription_prefs (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    network_id  TEXT NOT NULL REFERENCES networks(id),
    muted       BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, network_id)
);
```

#### Comparison

| Aspect | Per-capsule | Per-network |
|--------|-------------|-------------|
| Granularity | Fine: mute Peter's diet updates but keep his travel updates | Coarse: mute all updates from The Johnsons |
| Row count | O(users * capsules) worst case. 100 users * 1,000 capsules = 100K rows | O(users * networks). 100 users * 5 networks = 500 rows |
| Schema changes | New table + foreign key | New table + foreign key |
| Query at notification time | `SELECT muted FROM capsule_subscriptions WHERE user_id=? AND capsule_id=?` | `SELECT muted FROM network_subscription_prefs WHERE user_id=? AND network_id=?` |
| UX complexity | Per-capsule toggle in notification inbox | Per-network toggle in network settings |
| Migration path | Can be added incrementally | Fits existing network settings page |

#### Recommended: Per-network mute with per-capsule override

Start with per-network (simpler, lower row count, covers 90% of cases). Add per-capsule as an escalation path.

```sql
-- Phase 1: per-network (ship first)
CREATE TABLE network_subscription_prefs (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(18)))),
    user_id     TEXT NOT NULL REFERENCES users(id),
    network_id  TEXT NOT NULL REFERENCES networks(id),
    muted       BOOLEAN DEFAULT FALSE,
    mute_until  TIMESTAMP,  -- NULL = permanent, or temporary snooze
    UNIQUE(user_id, network_id)
);

-- Phase 2: per-capsule override (add when users ask for it)
CREATE TABLE capsule_subscriptions (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(18)))),
    user_id     TEXT NOT NULL REFERENCES users(id),
    capsule_id  TEXT NOT NULL REFERENCES knowledge_capsules(id),
    muted       BOOLEAN DEFAULT FALSE,
    UNIQUE(user_id, capsule_id)
);
```

**Notification filter logic** (on the receiving pod):

```python
async def should_deliver_notification(
    db: AsyncSession, user_id: str, capsule_id: str, network_ids: list[str]
) -> bool:
    """Check if a notification should be delivered to this user.

    Priority: per-capsule override > per-network pref > default (deliver)
    """
    # Phase 2: per-capsule override (most specific wins)
    capsule_pref = await db.execute(
        select(CapsuleSubscription.muted)
        .where(CapsuleSubscription.user_id == user_id,
               CapsuleSubscription.capsule_id == capsule_id)
    )
    cap_row = capsule_pref.scalar_one_or_none()
    if cap_row is not None:
        return not cap_row  # explicit capsule preference

    # Phase 1: per-network mute
    net_prefs = await db.execute(
        select(NetworkSubscriptionPref)
        .where(NetworkSubscriptionPref.user_id == user_id,
               NetworkSubscriptionPref.network_id.in_(network_ids))
    )
    for pref in net_prefs.scalars():
        if pref.muted:
            # Check temporary snooze expiry
            if pref.mute_until and pref.mute_until < utcnow():
                continue  # Snooze expired, deliver
            return False  # Muted

    return True  # Default: deliver
```

#### Read-only consumers vs write-capable owners

This distinction simplifies the subscription model significantly:

| Role | Can trigger propagation? | Receives notifications? | Can mute? |
|------|-------------------------|------------------------|-----------|
| **Owner** | Yes (updates capsule) | N/A (you are the source) | N/A |
| **Delegate** (`SharingDelegate` model) | Yes (on behalf of owner) | Yes (for other delegates' changes) | Yes |
| **Network member** (read-only) | No | Yes | Yes |
| **Ghost user** (remote member) | No (their pod is read-only for this data) | Yes (via federation) | Yes (on their pod) |

Because only owners and delegates can write, the notification direction is strictly one-way: owner's pod -> member pods. Members never push back. This eliminates an entire class of cycle bugs and keeps the subscription model simple.

---

### 5. Conflict Resolution (Concurrent Updates)

#### The Scenario

```
t=0s    Peter updates his diet on his pod (:9002)
t=2s    Rose updates her dinner menu on her pod (:9004)
t=5s    Peter's propagation arrives at Molly's pod (:9001)
t=6s    Rose's propagation arrives at Molly's pod (:9001)
        Both affect Molly's "San Sebastian itinerary" capsule.
```

Should Molly's agent process both updates in one pass, or sequentially?

#### Design: Debounced Timeline Coalescing

The receiving pod (Molly's) already has a debounce mechanism via the timeline engine. When two propagation notifications arrive within a short window, the timeline should coalesce them:

```python
# On Molly's pod, receiving two notifications:

# Notification 1 (from Peter's pod):
TimelineEntry(
    trigger_event_type="capsule.propagated.family",
    hook_prompt="Peter updated his dining preferences. Check itinerary.",
    source_pod="http://localhost:9002",
    received_at=t+5s,
)

# Notification 2 (from Rose's pod):
TimelineEntry(
    trigger_event_type="capsule.propagated.family",
    hook_prompt="Rose updated her dinner menu. Check itinerary.",
    source_pod="http://localhost:9004",
    received_at=t+6s,
)

# Timeline engine coalescing (5s window):
# Both entries have the same trigger_event_type and affect the same user.
# Coalesce into a single agent invocation:

CoalescedHookPrompt = """
Multiple network members updated shared data:
1. Peter updated his dining preferences (diet change)
2. Rose updated her dinner menu

Your 'San Sebastian itinerary' may be affected by both changes.
Steps:
1. query_peer peter — get updated diet
2. query_peer rose — get updated dinner menu
3. Check for conflicts between Peter's new diet and Rose's menu
4. Update the itinerary if needed
5. Save and share with The Johnsons
"""
```

#### Conflict detection via `updated_at` timestamps

TrustMesh capsules already have `updated_at` (auto-set by SQLAlchemy's `onupdate=utcnow`). The propagation payload includes this timestamp:

```python
# In /api/pod/notify payload:
{
    "capsules": [
        {
            "capsule_id": "...",
            "title": "Peter's Dining Preferences",
            "updated_at": "2026-03-28T10:00:00Z",  # from the source pod
        }
    ]
}
```

The receiving pod compares this against its last-known state:

```python
# Staleness check on Molly's pod:
# Molly's itinerary was last updated at 2026-03-25T14:00:00Z
# Peter's diet was updated at 2026-03-28T10:00:00Z (newer)
# Rose's menu was updated at 2026-03-28T10:00:02Z (also newer)
# Both are newer than the itinerary -> both are relevant
```

#### Last-write-wins vs Merge Strategy

| Strategy | Behavior | Risk | When to use |
|----------|----------|------|-------------|
| **Last-write-wins** | Agent processes the most recent notification, ignores older ones | Data loss if older update was more important | Never for TrustMesh (each update may affect different aspects) |
| **Merge (coalesce)** | Agent processes all pending updates in one pass | Higher LLM token cost (longer prompt) | Always recommended |
| **Sequential** | Agent processes each notification one-by-one | Potentially redundant work (update itinerary twice) | Fallback if coalescing fails |

**Recommendation: Merge (coalesce) with a 5-second timeline window.** The agent sees all pending updates at once and makes one holistic decision. This is both more efficient (one LLM call instead of two) and produces better results (the agent sees the full picture).

**Why not last-write-wins**: Peter's diet change and Rose's menu update affect different aspects of the itinerary. Dropping either one produces a stale result.

---

### 6. FTS5 Performance at Scale

#### Current implementation

The Zig kernel runs FTS5 with porter stemming and unicode61 tokenizer (`fts.zig:23-30`). The search function (`searchCapsules`) uses BM25 ranking with an `accessible_ids` allowlist passed as a JSON array:

```sql
SELECT capsule_id, bm25(capsule_fts) as rank
FROM capsule_fts
WHERE capsule_fts MATCH ?
  AND capsule_id IN (SELECT value FROM json_each(?))
ORDER BY rank
LIMIT ?
```

#### Benchmark expectations

| Capsule count | FTS5 MATCH time | JSON allowlist overhead | Total expected | Notes |
|---------------|----------------|------------------------|----------------|-------|
| 100 | <2ms | <1ms | **<5ms** | Single-user pod, typical |
| 500 | <5ms | <3ms | **<10ms** | Active family pod |
| 1,000 | <10ms | <8ms | **<20ms** | Power user |
| 5,000 | <30ms | <20ms | **<60ms** | Organization pod |
| 10,000 | <60ms | <40ms | **<120ms** | Large org, stress case |
| 50,000 | <200ms | <150ms | **<400ms** | Beyond personal agent use case |

These estimates are based on SQLite FTS5 benchmarks on ARM64 (Apple Silicon M-series). The `json_each()` allowlist is the bottleneck at scale because it creates a temporary table for each query. At 10,000+ accessible IDs, this dominates.

#### Staleness search specifics

When a propagation notification arrives ("Peter updated his diet"), the staleness search query is:

```
FTS5 MATCH: "peter OR diet OR dining OR preferences"
Accessible IDs: [all of Molly's capsule IDs]  (typically 50-200)
Top K: 10
```

This is well within the <10ms range for typical pod sizes. The staleness search is fast because:
1. The query is short (4-6 keywords extracted from the capsule title + category)
2. The allowlist is small (one user's capsules, not the entire pod)
3. BM25 ranking is computed by SQLite's FTS5 engine in C (called from Zig, zero-copy)

#### Optimization 1: Category-scoped FTS5 search

Already partially implemented. The `capsule_fts` table has a `category` column (UNINDEXED). We can add a pre-filter:

```sql
-- Current (searches all, filters by ID allowlist):
WHERE capsule_fts MATCH ? AND capsule_id IN (SELECT value FROM json_each(?))

-- Optimized (category pre-filter reduces MATCH candidates):
WHERE capsule_fts MATCH ? AND category = ? AND capsule_id IN (SELECT value FROM json_each(?))
```

To make this work efficiently, `category` needs to be a regular (non-UNINDEXED) column, or we need a separate content table with a category index. For FTS5, the better approach is:

```sql
-- Add a category filter as a column filter in the MATCH expression:
WHERE capsule_fts MATCH 'category:family AND (peter OR diet OR dining)'
```

This leverages FTS5's built-in column filtering, which is faster than a post-filter.

**Expected improvement**: 2-5x for pods with diverse categories (medical, financial, family, work capsules where only family is relevant to the staleness search).

#### Optimization 2: Bloom filter for pod-level capsule existence

Before making a federation call to Molly's pod, Peter's pod could check: "Does Molly's pod have ANY capsules that reference Peter?"

A Bloom filter answers this in O(1) with a small false-positive rate:

```
Data structure: 1KB Bloom filter per pod (covers ~1000 capsule owner references)
Populated: When a pod receives a query_peer result, it adds the referenced owner's username
Checked: Before sending /api/pod/notify
False positive rate: ~1% at 1000 entries with 1KB filter

Cost: 1KB * P pods = 200KB memory for 200 pods
Benefit: Eliminates unnecessary federation calls to pods that have no relevant capsules
```

**Implementation in Zig** (natural fit for bit manipulation):

```zig
pub const BloomFilter = struct {
    bits: [1024]u8,  // 8192 bits = 1KB

    pub fn insert(self: *BloomFilter, key: []const u8) void {
        const h1 = std.hash.CityHash64.hash(key);
        const h2 = std.hash.Murmur2_64.hash(key);
        for (0..4) |i| {
            const idx = (h1 +% i *% h2) % 8192;
            self.bits[idx / 8] |= @as(u8, 1) << @intCast(idx % 8);
        }
    }

    pub fn mightContain(self: *const BloomFilter, key: []const u8) bool {
        const h1 = std.hash.CityHash64.hash(key);
        const h2 = std.hash.Murmur2_64.hash(key);
        for (0..4) |i| {
            const idx = (h1 +% i *% h2) % 8192;
            if (self.bits[idx / 8] & (@as(u8, 1) << @intCast(idx % 8)) == 0)
                return false;
        }
        return true;
    }
};
```

**When to use**: Phase 2 optimization. Not needed for personal pods (P < 20), valuable for organizational deployments (P > 50).

#### Optimization 3: Pre-computed dependency graph

A Zig-side in-memory graph that tracks "capsule A references content from user B":

```
Node: capsule_id
Edge: capsule_id -> owner_username (extracted from capsule content at index time)

Example:
  molly_itinerary -> ["peter", "rose", "david"]
  rose_dinner_menu -> ["peter", "molly"]
```

When Peter's diet changes, the staleness search becomes a graph lookup: "Which capsules reference peter?" Answer: `molly_itinerary`, `rose_dinner_menu`. No FTS5 search needed.

**Trade-off**: Requires extracting person references at capsule index time (NER-like). Could use simple heuristics: if a capsule contains a username or display_name that matches a network member, add an edge.

**When to build**: Phase 3. Current FTS5 is fast enough for personal pods. The dependency graph becomes valuable when pods have 1,000+ capsules and staleness searches need to be sub-millisecond.

#### When to move beyond FTS5

FTS5 handles keyword-based staleness detection well. But it misses semantic relationships:

```
Peter's capsule: "I now eat fish and seafood"
Molly's capsule: "Restaurant booking at La Vieja (traditional Basque cuisine)"

FTS5 MATCH "peter fish seafood" -> NO MATCH on Molly's capsule
(No overlapping keywords)

Semantic search: "diet change to pescatarian" ~ "traditional cuisine" -> MATCH
(Conceptual overlap: diet affects restaurant choice)
```

**Upgrade path**: Add optional Voyage AI embeddings (already supported via `VOYAGE_API_KEY` env var) for semantic staleness detection alongside FTS5 keyword matching.

| Detection method | Latency | Precision | Recall | Cost |
|-----------------|---------|-----------|--------|------|
| FTS5 keyword | <10ms | High (exact matches) | Medium (misses semantic) | Free (in-process) |
| Voyage AI embeddings | 50-200ms | Medium | High (semantic matches) | $0.0001/query |
| Combined (FTS5 + embeddings) | 50-200ms | High | High | $0.0001/query |

**Recommendation**: FTS5-first, embeddings as enrichment. Run FTS5 for the fast path. If FTS5 returns zero results but the propagation is `broadcast` (safety-critical), fall back to embedding similarity search.

---

### 7. Zig vs Python Optimization Boundary

The core principle: **Zig handles the hot path (storage, search, membership resolution). Python handles the smart path (inference, agents, external APIs).**

#### What should move from Python to Zig

| Operation | Current | Proposed | Rationale |
|-----------|---------|----------|-----------|
| **Membership resolution** (N networks, M members, P pods) | Python SQLAlchemy (async SQL) | Zig SQL query (direct SQLite) | Single SQL query returns all pod URLs. Avoids ORM overhead, N+1 queries, and Python GIL. Zig already has DB handle open. |
| **Debounce buffer** | Python asyncio (recommended above) | Stay in Python | Timer-based, fires infrequently. Not worth FFI overhead. |
| **Staleness search** | Zig FTS5 (already done) | Keep in Zig | Zero-copy BM25 ranking, no Python involvement. |
| **Propagation depth tracking** | Not implemented | Zig (integer in notify payload) | Simple counter, parsed in Zig HTTP handler. No Python needed. |
| **Bloom filter** | Not implemented | Zig | Bit manipulation, hash functions. Natural fit for Zig's zero-alloc model. |
| **Dependency graph** | Not implemented | Zig | In-memory graph, updated at FTS5 index time. Zig's arena allocator is ideal. |

**Zig membership resolution** (move from Python):

```zig
// New export: podos_resolve_propagation_targets
// Input: capsule_id
// Output: JSON array of {pod_url, user_ids} grouped by pod
//
// Single SQL query:
//   SELECT DISTINCT u.remote_pod_url, u.id
//   FROM capsule_network_access cna
//   JOIN network_memberships nm ON nm.network_id = cna.network_id
//   JOIN users u ON u.id = nm.user_id
//   WHERE cna.capsule_id = ?
//     AND u.is_remote = 1
//     AND u.remote_pod_url IS NOT NULL
//   ORDER BY u.remote_pod_url

pub fn resolvePropagationTargets(
    database: *Database,
    capsule_id: [*]const u8,
    id_len: usize,
    out_buf: [*]u8,
    out_capacity: usize,
) !usize {
    // ... single prepared statement, JSON output to buffer
}
```

This replaces three Python queries (capsule -> networks -> memberships -> users) with one Zig SQL query. Expected improvement: 5-10x for the membership resolution step.

#### What stays in Python

| Operation | Why Python |
|-----------|-----------|
| `_infer_propagation()` | NLP-like keyword matching. Needs flexibility for rapid iteration. Adding a new keyword pattern is a one-line Python change vs recompiling Zig. |
| Agent hook generation | LLM prompt engineering. Prompts change frequently. Python string formatting is more maintainable. |
| Federation HTTP calls | Python `httpx` with retry, backoff, timeout. Zig's HTTP client is not as mature for outbound calls with complex retry logic. |
| TinyFish / browse_web calls | Python `aiohttp`. External API integration with JSON parsing, error handling. |
| Notification filtering (mute/subscribe) | Business logic that changes with UX requirements. Python's flexibility > Zig's performance here. |
| Conflict coalescing | Timeline engine logic. Runs once per debounce window (5s), not per-request. |

#### The boundary visualized

```
┌─────────────────────────────────────────────────────────────┐
│  Python Layer (intelligence + external I/O)                 │
│                                                             │
│  _infer_propagation()    Federation HTTP    Agent hooks     │
│  Notification filtering  TinyFish calls     LLM prompts    │
│  PropagationBatcher      Conflict coalesce  Mute/subscribe  │
│         │                      │                  │         │
│         ▼ ctypes FFI           ▼ httpx            ▼         │
├─────────────────────────────────────────────────────────────┤
│  Zig Kernel (hot path + storage)                            │
│                                                             │
│  FTS5 search             Membership SQL     Transit encrypt │
│  Bloom filter            Depth tracking     Dependency graph│
│  Capsule CRUD            Session auth       HTTP routing    │
│                                                             │
│  ┌──────────────┐                                           │
│  │  SQLite DB   │  WAL mode, shared between Zig + Python   │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
```

---

### 8. Read-Only vs Write-Owner Model

#### The Invariant

> **Peter's pod is the ONLY source of truth for Peter's data.**

This is the foundational invariant of TrustMesh's federation model. It has profound implications for propagation.

#### Data ownership model

```
Peter's Pod (:9002)                     Molly's Pod (:9001)
┌──────────────────────┐                ┌──────────────────────┐
│ Peter (owner)        │                │ Molly (owner)        │
│  ├─ Diet capsule  [W]│───notify──────>│  ├─ Itinerary    [W] │
│  ├─ Travel prefs  [W]│                │  ├─ Budget       [W] │
│  └─ Allergies     [W]│                │  └─ Notes        [W] │
│                      │                │                      │
│ Molly (ghost)     [R]│<──query_peer───│ Peter (ghost)     [R]│
│ Rose (ghost)      [R]│                │ Rose (ghost)      [R]│
└──────────────────────┘                └──────────────────────┘

[W] = writable (owner or delegate)
[R] = read-only (ghost user, no local capsules)
```

Ghost users on a pod have no capsules. They are identity placeholders for trust resolution (`resolve_trust_level` in `trust.py` checks ghost users' `remote_pod_url` and `remote_did`). When Molly's agent needs Peter's data, it calls `query_peer` which makes a federation HTTP call to Peter's pod. The response is never persisted as a local capsule on Molly's pod.

#### How ownership affects propagation

| Actor | Action | Triggers propagation? | Mechanism |
|-------|--------|-----------------------|-----------|
| **Owner** updates their capsule | Peter edits his diet on his pod | Yes | Owner's pod runs `PropagationBatcher.enqueue()` |
| **Delegate** updates on behalf of owner | Rose (delegate for Peter's health category) updates Peter's medication list | Yes | Same as owner, but `changed_by` in `CapsuleVersion` records the delegate's user_id |
| **Reader** queries via `query_peer` | Molly asks Peter's agent about his diet | No | Read-only. No state change on Peter's pod. |
| **Reader's agent** updates its OWN capsule based on query result | Molly's agent updates her itinerary after learning Peter's diet changed | Yes (for Molly's capsule) | Molly's pod propagates the itinerary change to her network members. Depth tracking prevents cascade back to Peter. |

#### Delegate propagation detail

The `SharingDelegate` model (already in `models.py`) allows delegation:

```python
# Rose is a delegate for Peter's health capsules
SharingDelegate(
    owner_id=peter.id,
    delegate_user_id=rose.id,
    category="health",
)
```

When Rose updates Peter's medication capsule via a cross-pod delegate action:

1. Rose's pod sends a signed `POST /api/pod/delegate_update` to Peter's pod
2. Peter's pod verifies Rose's delegate authority for the `health` category
3. Peter's pod updates the capsule (Peter is still the owner)
4. Peter's pod runs propagation (because the capsule changed)
5. The notification says "Peter's medication list was updated" (not "Rose updated...") -- the owner is the identity for propagation

This preserves the invariant: Peter's pod is the source of truth, even when a delegate makes the change.

#### Federation implication: no writable copies

Unlike Git (distributed copies with push/pull), TrustMesh has a strict hub-and-spoke model per user:

```
         ┌─────────────┐
         │ Peter's Pod  │ (source of truth)
         │  [writable]  │
         └──────┬───────┘
                │
       ┌────────┼────────┐
       │        │        │
       ▼        ▼        ▼
   ┌───────┐ ┌───────┐ ┌───────┐
   │Molly's│ │Rose's │ │David's│
   │  Pod  │ │  Pod  │ │  Pod  │
   │ [read]│ │ [read]│ │ [read]│
   └───────┘ └───────┘ └───────┘

Data flow: Peter -> everyone (push via propagation)
Query flow: everyone -> Peter (pull via query_peer)
Never: Molly -> Rose for Peter's data (always go to source)
```

This means:
- **No merge conflicts** on Peter's data (single writer)
- **No vector clocks** needed (no concurrent writes to the same data)
- **No consensus protocol** needed (no distributed agreement on Peter's state)
- **Propagation is strictly one-directional**: source pod pushes, member pods receive
- **Staleness is always detectable**: compare `updated_at` from the source pod against the last `query_peer` timestamp on the receiving pod

The only conflict scenario (addressed in Section 5) is when multiple owners' changes affect a third party's capsule (Peter's diet + Rose's menu -> Molly's itinerary). But this is a **merge of different owners' data**, not a conflict on the same data. The coalescing approach handles it correctly.

---

### Performance Summary Table

| Scenario | No optimization | With batching | With batching + Zig membership | With all optimizations |
|----------|----------------|---------------|-------------------------------|----------------------|
| 1 capsule, 8 members, 4 pods | 4 HTTP calls, ~60ms | 4 HTTP calls, ~60ms | 4 HTTP calls, ~55ms | 4 HTTP calls, ~55ms |
| 10 capsules, 100 members, 16 pods | 160 HTTP calls, ~2.4s | 16 HTTP calls, ~240ms | 16 HTTP calls, ~200ms | 16 HTTP calls, ~180ms |
| 100 capsules, 100 members, 16 pods | 1,600 HTTP calls, ~24s | 16 HTTP calls, ~240ms | 16 HTTP calls, ~200ms | ~12 HTTP calls, ~150ms (Bloom filter eliminates 4 pods) |
| 10,000 capsules, 1,000 members, 200 pods | 2M HTTP calls, FAIL | 200 HTTP calls, ~1.5s | 200 HTTP calls, ~800ms | ~120 HTTP calls, ~500ms (Bloom + dependency graph) |

**Key takeaway**: Batching alone gets us from catastrophic (2M calls) to manageable (200 calls). The Zig optimizations (membership resolution, Bloom filter, dependency graph) provide diminishing but meaningful returns at the high end. For TrustMesh's target use case (personal AI agents, 5-50 network members), batching is sufficient through Series A scale.

---

## Three-Tier Propagation Model

TrustMesh has three distinct layers, each with different trust, visibility, and propagation semantics. Propagation must respect the boundaries between them.

```
┌─────────────────────────────────────────────────────────┐
│           LAYER 3: AGENT REGISTRY (public)              │
│  registry.trustmesh.ai (:9100)                          │
│  - Public agent cards (DID, capabilities, pod URL)      │
│  - Discovery: "find agents that know about eldercare"   │
│  - NO capsule data here — just agent metadata           │
│  - Anyone can query; no trust required                  │
└────────────────────────┬────────────────────────────────┘
                         │ register / discover
┌────────────────────────┴────────────────────────────────┐
│           LAYER 2: FEDERATION (pool of pods)             │
│  Trust networks span pods via ghost users                │
│  - "The Johnsons" pool: Peter(:9002), Molly(:9001),     │
│    Rose(:9004), Jane(:9003)                              │
│  - query_peer crosses pod boundaries                     │
│  - Trust level: network > connected > public             │
│  - Capsule data decrypted at source, never copied        │
└──┬──────────────┬──────────────┬───────────────────┬────┘
   │              │              │                   │
┌──┴───┐   ┌──────┴───┐   ┌─────┴────┐   ┌─────────┴──┐
│:9001 │   │  :9002   │   │  :9004   │   │   :9003    │
│Molly │   │  Peter   │   │  Rose    │   │   Jane     │
│Pod   │   │  Pod     │   │  Pod     │   │   Pod      │
│      │   │          │   │          │   │            │
│LAYER1│   │ LAYER 1  │   │ LAYER 1  │   │  LAYER 1   │
│Local │   │ Local    │   │ Local    │   │  Local     │
│vault │   │ vault    │   │ vault    │   │  vault     │
└──────┘   └──────────┘   └──────────┘   └────────────┘
```

### Layer 1: Pod Level (private)

**What lives here**: User's capsules, vault keys, agent, local connections, local network memberships, notifications, timeline entries.

**Propagation at this layer**: Within the same pod (single-pod mode where multiple users share a pod, e.g., the original `seed.py` family pod):

| Event | Propagation | Mechanism |
|-------|-------------|-----------|
| Capsule created/updated | Notification to local network members | Direct DB insert into `notifications` table |
| Staleness detection | FTS5 search on local capsules | Zig kernel, <10ms |
| Agent re-trigger | Timeline entry with hook_prompt | Local async task |

**Cost**: O(M) where M = local network members. Fast — no HTTP, no federation, just DB writes.

**Zig role**: FTS5 staleness search, membership resolution (SQL join on `network_memberships` + `capsule_network_access`), notification insert. All in-process, zero network overhead.

**Who can write**: Only the capsule owner. `SharingDelegate` model allows designated users to update on behalf of the owner (e.g., Molly can update Rose's care routine).

**Who can read**: Depends on capsule visibility:
- `private` → owner only
- `internal` → owner + network members (resolved via `network_memberships`)
- `open` → anyone on this pod

### Layer 2: Federation (pool of pods)

**What lives here**: Ghost users (`is_remote=True`), peer pod connections (`PeerPod` model), cross-pod network memberships (created by orchestrator's `pool-sync`).

**Propagation at this layer**: Crosses pod boundaries. This is where it gets interesting.

| Event | Propagation | Mechanism |
|-------|-------------|-----------|
| Capsule updated on Pod A | Notify ghost users that represent remote members | `POST /api/pod/notify` to each peer pod |
| Remote pod receives notification | Create local notification + staleness search | Receiving pod processes like a local event |
| Staleness detected on remote pod | Timeline trigger on the receiving pod | The RECEIVING pod's agent acts, not the source |

**Critical invariant**: Data never leaves the source pod as a copy. Peter's capsule content is ONLY decrypted on Peter's pod. When Molly's agent calls `query_peer(peter)`, Peter's pod decrypts and responds — Molly gets the answer text, not the encrypted capsule. Propagation sends a NOTIFICATION (metadata: "Peter updated X"), not the data itself.

**Cost**: O(P) where P = distinct peer pods in the affected networks. Each pod gets ONE batched notification per debounce window, regardless of how many capsules changed or how many ghost users are on that pod.

**Zig role at this layer**:
- Resolve which ghost users are in which networks: SQL query on `network_memberships WHERE user.is_remote = 1`, grouped by `remote_pod_url`
- Deduplicate: one HTTP call per pod, not per ghost user
- This query can be a Zig-native SQL execution returning `{pod_url: [affected_capsule_ids]}` — Python just iterates and sends

**Who can write**: Only the capsule owner's pod. Federation is read-only for consumers. Molly's pod CANNOT update Peter's capsule. Molly's agent can only ask Peter's agent, and Peter's agent decides what to share.

**Who can read**: Determined by trust level:
- `network` trust → internal + open capsules shared to common networks
- `connected` trust → open capsules only
- `public` trust → open capsules only

**Propagation flow**:
```
Peter updates capsule on :9002 (propagation=notify)
  │
  ├─ Zig: resolve ghost members in capsule's networks
  │   → SELECT DISTINCT remote_pod_url FROM users u
  │     JOIN network_memberships nm ON nm.user_id = u.id
  │     JOIN capsule_network_access cna ON cna.network_id = nm.network_id
  │     WHERE cna.capsule_id = ? AND u.is_remote = 1
  │   → Returns: [http://localhost:9001, http://localhost:9004]
  │
  ├─ Python: batch + send to each pod
  │   → POST http://localhost:9001/api/pod/notify (Molly's pod)
  │   → POST http://localhost:9004/api/pod/notify (Rose's pod)
  │
  ├─ Molly's pod (:9001) receives:
  │   → Creates Notification for molly
  │   → Zig FTS5: search molly's capsules for "peter" + "travel" + "dining"
  │   → Finds: itinerary capsule → mark stale
  │   → Timeline entry → agent re-triggers
  │
  └─ Rose's pod (:9004) receives:
      → Creates Notification for grandmarose
      → Zig FTS5: search rose's capsules for "peter" + "dining"
      → No matches (Rose doesn't have an itinerary) → no action
```

### Layer 3: Agent Registry (public)

**What lives here**: Public agent metadata — DID, display name, capabilities, pod URL, `is_discoverable` flag. Stored in the registry at `:9100` (Next.js + SQLite).

**NO capsule data lives here**. The registry is a phone book, not a vault.

**Propagation at this layer**: Minimal. The registry doesn't know about capsule updates. But there ARE registry-level events that matter:

| Event | Propagation | Mechanism |
|-------|-------------|-----------|
| New agent registered | Discoverable by any pod via `/api/agents` search | Registry stores it; pods pull on demand |
| Agent capabilities changed | Registry updated; pods re-discover on next search | No push — pull-based |
| Agent went offline | Registry health check fails; marked unavailable | Registry polls pod health |
| Pod URL changed | Agent re-registers with new URL | Pod pushes to registry |

**Registry does NOT propagate capsule changes.** It doesn't know about them and shouldn't. The registry is Layer 3 — it only knows "this agent exists at this URL with these capabilities."

**However**, the registry matters for propagation in one case: **discovery-driven propagation**. If Peter joins a new public network (e.g., "Bay Area Foodies") and makes his dining preferences discoverable, the registry announces his agent's capabilities. Other agents can then discover and query him. But this is pull-based (other agents choose to query), not push-based (Peter doesn't push to strangers).

### Cross-Layer Propagation Rules

| From → To | Allowed? | Mechanism | Example |
|-----------|----------|-----------|---------|
| Pod → Pod (Layer 1 → 1) | Only via federation (Layer 2) | `POST /api/pod/notify` | Peter's diet change → notify Molly |
| Pod → Registry (Layer 1 → 3) | Only agent metadata | `POST /api/agents` (registration) | Peter's pod registers his agent |
| Registry → Pod (Layer 3 → 1) | Pull only | Pod queries `GET /api/agents?q=...` | Molly's agent discovers Peter via registry |
| Pod → Pod bypassing federation | NO | Blocked by SSRF + DID verification | Prevents unauthorized data access |
| Registry → Registry | N/A | Single registry instance | Not applicable |
| Capsule data through registry | NEVER | Registry has no capsule storage | Private data stays on pods |

### Data Sovereignty Enforcement

The three-tier model enforces a critical property: **data only flows outward with owner consent, never inward without authentication.**

```
WRITE direction (owner → world):
  Pod (owner writes) → Federation (notify network) → Registry (update capabilities)
  Each step requires owner action or owner-set propagation mode.

READ direction (world → owner):
  Registry (discover agent) → Federation (query_peer) → Pod (decrypt + respond)
  Each step requires trust level validation. Pod decides what to share.
```

**No layer can force data into a pod.** A remote pod can send a notification ("Peter updated X"), but the receiving pod's agent decides whether to act on it. Molly's agent might ignore Peter's update, or might re-plan the trip — that's Molly's agent's decision, not Peter's.

**No layer can extract data from a pod without trust.** Even if the registry lists Peter's agent, a stranger can only see `open` capsules. `internal` capsules require network membership. `private` capsules are invisible to everyone.

### Implications for Propagation Implementation

| Decision | Resolution |
|----------|-----------|
| Where does the `propagation` field live? | On the capsule (Layer 1). Each pod stores its own. |
| Where does notification fan-out happen? | Layer 1 (local members) + Layer 2 (federation push to peer pods). Never Layer 3. |
| Where does staleness detection happen? | Layer 1 only — each pod searches its own FTS5 index. |
| Where does the agent re-trigger happen? | Layer 1 only — the receiving pod's agent acts on its own timeline. |
| Does the registry need to know about propagation? | No. Registry is metadata only. |
| Can propagation cross trust boundaries? | No. A `notify` propagation only reaches members of the capsule's shared networks. It cannot notify someone outside the trust network. |
| What about public capsules? | `open` visibility capsules with `propagation=notify` only notify network members, not the entire world. Public means "readable by anyone who asks," not "push to everyone." |

---

## Roles, Delegation & Write Authority

### The Problem

Current model is simple: owner writes, everyone else reads. But real families don't work that way:
- Molly manages Grandma Rose's medical capsules (care routine, medications)
- Peter and Molly both manage the family vacation plans
- Dr. Lee needs to update Rose's medication list after an appointment
- The whole family should be able to contribute to a shared shopping list

We need roles beyond just "owner" and "reader" — but we can't break the sovereignty model where each pod owns its data.

### Role Hierarchy

```
OWNER (1 per capsule)
  └── Full control: read, write, delete, change visibility,
      change propagation, grant/revoke roles
      Lives on the capsule's pod.

ADMIN (granted by owner)
  └── Can: read, write, change visibility, grant editor role
      Cannot: delete capsule, change propagation mode, grant admin role
      Use case: Peter is admin of family vacation capsule that Molly owns

EDITOR (granted by owner or admin)
  └── Can: read, write (content only)
      Cannot: change visibility, propagation, roles, delete
      Use case: Dr. Lee can edit Rose's medication list

VIEWER (default for network members)
  └── Can: read (via query_peer)
      Cannot: write anything
      This is the current behavior for all network members.
```

### Where Roles Live

**Option A: On the capsule itself (per-capsule ACL)**

```python
class CapsuleRole(Base):
    __tablename__ = "capsule_roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    capsule_id: Mapped[str] = mapped_column(ForeignKey("knowledge_capsules.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20))  # admin | editor | viewer
    granted_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**Option B: On the network membership (per-network role)**

Already exists: `NetworkMembership.role` field (currently just "member"). Extend to:

```python
# network_memberships.role: "member" | "admin" | "editor"
```

Network admin → admin on ALL capsules shared to that network.

**Option C: Both (recommended)**

- `NetworkMembership.role` sets the default for all capsules in that network
- `CapsuleRole` overrides per-capsule when needed (e.g., Dr. Lee is editor of ONLY the medication capsule, not all health capsules)

Resolution order:
```
1. CapsuleRole for this user + capsule? → use it
2. NetworkMembership.role for shared networks? → use highest role
3. SharingDelegate for this category? → maps to editor
4. Default → viewer
```

### Existing `SharingDelegate` Integration

`SharingDelegate` already exists: "Molly is a health delegate for Rose." This maps to:

| SharingDelegate | Equivalent Role | Scope |
|---|---|---|
| `category="health"` | editor | All of Rose's health capsules |
| `category="*"` | admin | All of Rose's capsules |

We keep `SharingDelegate` as a convenience layer — it auto-grants editor/admin role at the category level without needing per-capsule `CapsuleRole` entries.

### The Hard Part: Cross-Pod Write Path

Today, federation is read-only. If Molly (on :9001) is an editor of Rose's medication capsule (on :9004), how does Molly's write get applied?

**Approach: Federated Write Request**

```
Molly's agent on :9001 wants to update Rose's capsule
  │
  ├─ Molly's pod sends:
  │   POST http://localhost:9004/api/pod/write
  │   {
  │     "from_did": "did:key:z6Mk...molly",
  │     "from_pod": "http://localhost:9001",
  │     "capsule_id": "rose-meds-capsule-id",
  │     "action": "update",
  │     "content": "Updated medication list...",
  │     "signature": "<ed25519 sig of payload>"
  │   }
  │
  ├─ Rose's pod (:9004) receives:
  │   1. Verify DID signature (is this really Molly?)
  │   2. Resolve Molly's role on this capsule:
  │      → CapsuleRole? SharingDelegate? NetworkMembership?
  │   3. Check: does the role allow "update content"?
  │   4. If yes: decrypt capsule, apply update, re-encrypt, save
  │   5. Fire propagation (if capsule.propagation != "silent")
  │   6. Respond: { "success": true, "version": 4 }
  │
  └─ Molly's pod gets confirmation → updates any cached references
```

**Critical: the write happens on Rose's pod, not Molly's.** Molly sends a WRITE REQUEST. Rose's pod validates it, applies it, and handles encryption/propagation. Molly never touches Rose's vault key or encrypted storage.

### Re-encryption on Role Changes

When roles change, encryption keys may need rotation.

**Scenario: Peter is removed as admin of the vacation capsule**

```
Before: Peter has admin role → can read + write → has network key
After:  Peter is revoked → should NOT be able to read cached content

But: Peter already saw the decrypted content during previous queries.
     You can't un-see data. Revoking access prevents FUTURE reads,
     not retroactive knowledge.
```

**Key rotation protocol:**

```
1. Owner (Molly) revokes Peter's admin role
2. Molly's pod generates a NEW network key for the affected network
3. Re-encrypt all capsules shared to that network with the new key
4. Distribute new key ONLY to remaining members:
   → Local members: update encrypted_network_key in NetworkMembership
   → Remote members: POST /api/pod/rekey to each peer pod
5. Peter's ghost user on other pods gets its encrypted_network_key cleared
6. Next time Peter's agent queries: trust resolution fails → no access
```

**Zig role in re-encryption:**

This is a Zig-heavy operation. The transit engine handles:
```
for each capsule shared to the re-keyed network:
  1. Decrypt with OLD network key (Zig transit engine)
  2. Re-encrypt with NEW network key (Zig transit engine)
  3. Update content_encrypted + content_hash in SQLite
  4. Update capsule FTS5 index (content unchanged, just re-encrypted)
```

Performance: Zig's AES-256-GCM runs at ~1GB/s. Re-encrypting 1000 capsules averaging 2KB each = 2MB of crypto work = ~2ms. The bottleneck is SQLite writes, not encryption.

**When re-encryption is NOT needed:**

| Event | Re-encrypt? | Why |
|-------|-------------|-----|
| Add editor to one capsule | No | They get read access via query_peer, no key needed |
| Add admin to network | No | Admin can query via federation, capsule stays encrypted on owner's pod |
| Remove viewer | No | They never had the key |
| Remove editor from capsule | No | They wrote via federated write, never had the vault key |
| Remove admin from network | **YES** | Admin may have had the network key for key-wrapping |
| Owner rotates vault key | **YES** | All capsules re-encrypted, all network keys re-wrapped |
| Network dissolved | No | Just delete network + memberships, capsules stay on owner's pod |

Key insight: **in the federated model, editors and admins write via `POST /api/pod/write` — they never hold the vault key.** Only the owner's pod has the vault key. So re-encryption is only needed when someone who had the NETWORK key (used for key-wrapping in `pool-sync`) is removed.

### Conflict Resolution with Multiple Writers

**Scenario: Peter and Molly both edit the vacation itinerary simultaneously**

Peter (admin, :9002 via federated write) changes Day 3 activities.
Molly (owner, :9001 directly) changes Day 3 restaurants.
Both write to Rose's pod at :9004... wait, the itinerary is on Molly's pod.

Actually: **the itinerary lives on the OWNER's pod.** If Molly owns it, both writes go to :9001. Even Peter's federated write goes to Molly's pod.

```
Peter's write request arrives at :9001 at T=100
Molly's direct write happens at :9001 at T=100.3

SQLite serializes them (WAL mode, single writer):
  → Peter's write: version 4, changes Day 3 activities
  → Molly's write: version 5, changes Day 3 restaurants
  → Both succeed — no conflict because different fields
```

**But what if they change the same field?**

```
Peter changes content: "Day 3: Hiking in the mountains"
Molly changes content: "Day 3: Vineyard tour"
  → Last-write-wins at the content level
  → version 5 (Molly) overwrites version 4 (Peter)
  → BUT: CapsuleVersion tracks both changes:
    version 4: changed_by=peter, content="Day 3: Hiking..."
    version 5: changed_by=molly, content="Day 3: Vineyard..."
```

**Resolution strategies (in order of complexity):**

| Strategy | How | When to use |
|----------|-----|-------------|
| **Last-write-wins** | SQLite serial writes, latest timestamp wins | Simple, works for most cases |
| **Version alert** | If version changed between read and write, warn the writer | "Peter updated this 3 seconds ago. Your changes may overwrite his." |
| **Field-level merge** | Parse content sections, merge non-conflicting changes | Complex — requires structured content format |
| **Agent-mediated merge** | Both versions sent to LLM: "Merge these two edits" | Most flexible, but slow and costs tokens |

**Recommended for v1: last-write-wins + version alert.** The `CapsuleVersion` table already tracks every change. If Peter's write creates version 4 and Molly's write sees that version 4 exists since her last read, the UI/agent warns: "Peter just edited this. Review before saving."

### How Roles Affect Propagation

| Actor | Action | Propagation fires? | Who gets notified? |
|-------|--------|--------------------|--------------------|
| Owner updates capsule | Yes (owner's propagation setting) | All network members |
| Admin updates capsule | Yes (same propagation setting) | All network members INCLUDING owner |
| Editor updates capsule | Yes (same propagation setting) | All network members INCLUDING owner |
| Viewer queries capsule | No | Nobody — reads don't propagate |
| Owner changes propagation mode | No notification for mode change itself | N/A |
| Admin grants editor role | Notify the new editor | Just the new editor |
| Owner revokes admin | Notify the revoked admin | Just the revoked admin + re-encryption if needed |

**Key detail: when an editor or admin updates a capsule, the OWNER gets notified too.** The owner should always know when someone else modifies their data. This is the `capsule_propagated` notification with `changed_by` field showing who made the edit.

### What Zig Owns vs Python — Role & Propagation Hot Path

Our Zig kernel already handles the performance-critical paths: `transit.zig` (keys never leave Zig memory), `trust.zig` (trust resolution via direct SQL), `fts.zig` (BM25 search), `session.zig` (O(1) token lookup), `sensitivity.zig` (zero-alloc keyword scan), `rate_limit.zig` (sliding window). The roles/propagation design should push MORE into Zig, not less.

**Principle: every operation that runs on EVERY request goes to Zig. Intelligence that runs on SOME requests stays in Python.**

#### Zig hot path additions (must be fast, runs constantly)

| Operation | Why Zig | Implementation |
|-----------|---------|----------------|
| **Role resolution** | Runs on every capsule read AND write. Must be <1ms. | New `roles.zig` module. Single SQL query with LEFT JOIN on `capsule_roles`, `network_memberships`, `sharing_delegates`. Returns highest role. C export: `podos_resolve_role(user_id, capsule_id) → u8` (0=none, 1=viewer, 2=editor, 3=admin, 4=owner) |
| **Write authorization** | Gate before every PUT/DELETE on capsules. | In `handlers/capsules.zig` `handleUpdateCapsule`: call `podos_resolve_role()`, reject if < editor. Zero-alloc — role check is a single SQL query + integer comparison |
| **Propagation target resolution** | After capsule update, find which pods to notify. | New function in `trust.zig`: `podos_propagation_targets(capsule_id) → [{pod_url, user_ids}]`. SQL join on `capsule_network_access` + `network_memberships` + `users WHERE is_remote`, grouped by `remote_pod_url`. Returns packed buffer for Python to iterate |
| **Re-encryption batch** | When admin removed, re-encrypt N capsules. | `transit.zig` already has `encryptForUser` / `decryptForUser`. New: `podos_rekey_capsules(network_id, old_key, new_key)` — iterates capsules in Zig, re-encrypts each, updates SQLite row. No Python round-trips. Target: 1000 capsules in <50ms |
| **DID signature verification** | On every `POST /api/pod/write`. | `federation_auth.zig` already has ed25519 verify. Reuse for write request signatures |
| **Staleness search** | FTS5 query on receiving pod. | `fts.zig` already has `podos_fts_search`. Add `podos_fts_search_by_owner(owner_username, category)` for targeted staleness detection |
| **Debounce buffer** | Batch notifications within 5s window. | New `propagation.zig`: ring buffer per pod_url, timer-based flush. When capsule updated → push to buffer. On timer → C callback to Python for HTTP send. Zig manages the timing; Python manages the HTTP |
| **Version conflict detection** | Compare `updated_at` on write request vs capsule's current version. | In `handlers/capsules.zig`: if request includes `expected_version` and it differs from DB, return 409 Conflict. Zero-cost — one SQLite read |

#### Python smart path (runs selectively, needs intelligence)

| Operation | Why Python | Implementation |
|-----------|------------|----------------|
| **`_infer_propagation()`** | NLP keyword matching, needs flexibility for new patterns | Python function with keyword lists |
| **Agent hook generation** | LLM prompt engineering — builds the `hook_prompt` for timeline entries | Python string templating |
| **Federation HTTP calls** | `POST /api/pod/notify`, `POST /api/pod/write` — needs retry, backoff, TLS | Python httpx with AsyncClient |
| **Staleness scoring** | Semantic analysis of whether FTS5 matches actually indicate affected data | Python — may use embeddings in future |
| **Agent re-trigger orchestration** | Decides whether to re-query, re-research, or just notify | Agent prompt + tool loop |
| **TinyFish API calls** | External API, SSE streaming, needs aiohttp | Python async |
| **Role grant/revoke logic** | Business rules (who can grant what to whom) | Python route handlers |

#### The Zig-Python boundary for a federated write

```
External pod sends POST /api/pod/write to Rose's pod (:9004)

Zig HTTP layer receives request (server_main.zig)
  │
  ├─ [ZIG] Parse JSON body (json.zig — zero-alloc streaming parser)
  ├─ [ZIG] Verify ed25519 DID signature (federation_auth.zig)
  ├─ [ZIG] Resolve role: podos_resolve_role(from_user_id, capsule_id)
  │   → SQL: SELECT role FROM capsule_roles WHERE user_id=? AND capsule_id=?
  │          UNION SELECT role FROM network_memberships nm
  │            JOIN capsule_network_access cna ON cna.network_id = nm.network_id
  │            WHERE nm.user_id=? AND cna.capsule_id=?
  │          UNION SELECT '*' as role FROM sharing_delegates
  │            WHERE delegate_user_id=? AND (category=capsule.category OR category='*')
  │          ORDER BY CASE role WHEN 'admin' THEN 3 WHEN 'editor' THEN 2 ELSE 1 END DESC
  │          LIMIT 1
  │   → Returns: 2 (editor) — fast, single query
  │
  ├─ [ZIG] Authorization check: editor >= required_role(action="update")? YES
  ├─ [ZIG] Decrypt capsule content (transit.zig — key stays in Zig memory)
  ├─ [ZIG] Apply new content
  ├─ [ZIG] Re-encrypt with owner's vault key (transit.zig)
  ├─ [ZIG] Update SQLite row (content_encrypted, content_hash, updated_at, version)
  ├─ [ZIG] Update FTS5 index (fts.zig)
  ├─ [ZIG] Read capsule.propagation field
  │
  ├─ IF propagation != "silent":
  │   ├─ [ZIG] Resolve propagation targets (trust.zig)
  │   │   → SQL: grouped pod_urls of ghost members in capsule's networks
  │   ├─ [ZIG] Push to debounce buffer (propagation.zig)
  │   └─ [ZIG → PYTHON callback] On debounce flush: Python sends HTTP notifications
  │
  └─ [ZIG] Respond: 200 { success: true, version: 5 }

Total Zig hot-path operations: ~7 (parse + verify + resolve + auth + decrypt + encrypt + write)
Total Python involvement: 0 (for the write itself) — only later for HTTP notification fan-out
```

This is the key optimization: **the entire write path stays in Zig**. Python is never in the critical path for a federated write. Python only handles the async notification delivery after the write is confirmed.

#### Existing Zig capabilities we leverage

| Existing module | Leveraged for |
|-----------------|---------------|
| `transit.zig` — `encryptForUser()`, `decryptForUser()`, `rotateKey()` | Re-encryption on role revocation. `rotateKey()` already exists for key rotation. |
| `crypto.zig` — ed25519 verify, AES-256-GCM | DID signature verification on federated writes. Already used in federation_auth. |
| `fts.zig` — `podos_fts_search()`, BM25 ranking | Staleness detection. Already category-scoped. Add owner-scoped variant. |
| `trust.zig` — `resolveTrustLevel()` | Foundation for `resolveRole()`. Same pattern: SQL join → return enum. |
| `session.zig` — O(1) StringHashMap | Model for debounce buffer: pod_url → pending notifications. Same data structure pattern. |
| `rate_limit.zig` — sliding window | Model for propagation throttling: max N notifications per pod per minute. |
| `sensitivity.zig` — zero-alloc keyword scan | Model for `_infer_propagation()` if we want to move it to Zig for speed (compile-time keyword lists). |
| `handlers/capsules.zig` — full CRUD | Add role check at the top of `handleUpdateCapsule`. ~20 lines of new code. |
| `db.zig` — prepared statements | All new SQL queries use prepared statements. No SQL injection, no allocation per query. |

### Implementation Summary

| Component | What to build | Layer | Zig or Python |
|-----------|---------------|-------|---------------|
| `capsule_roles` table | Schema + model | Storage | Zig schema, Python model |
| `NetworkMembership.role` extension | "member" → "member/editor/admin" | Storage | Zig migration |
| `roles.zig` module | `podos_resolve_role()` — single SQL → role enum | Hot path | **Zig** |
| `propagation.zig` module | Debounce buffer + timer flush | Hot path | **Zig** |
| Role check in `handleUpdateCapsule` | Gate writes by role | Hot path | **Zig** |
| Version conflict check | `expected_version` vs current | Hot path | **Zig** |
| `podos_rekey_capsules()` | Batch re-encrypt on key rotation | Bulk op | **Zig** |
| `podos_propagation_targets()` | Resolve pod URLs for notification | Query | **Zig** |
| `POST /api/pod/write` handler | Parse + verify + role + write + respond | Handler | **Zig** (full handler in Zig, like other handlers) |
| `POST /api/pod/notify` handler | Receive notification from peer | Handler | **Python** (creates Notification + triggers staleness search) |
| `_infer_propagation()` | NLP keyword detection | Intelligence | Python |
| Staleness scoring | Evaluate FTS5 matches for relevance | Intelligence | Python |
| Agent hook generation | Build `hook_prompt` for timeline | Intelligence | Python |
| Federation HTTP send | Notification delivery to peer pods | Network I/O | Python (httpx) |
| TinyFish re-trigger | Agent decides + calls browse_web | Intelligence | Python |
| UI role management | Grant/revoke in capsule editor | Frontend | TypeScript |
| CLI `vault grant` / `vault propagate` | Role + propagation commands | CLI | Python (typer) |

---

## Research-Backed Design Rationale, Security Model & DRY Audit

This section grounds the propagation design in real language characteristics, published benchmarks, and concrete threat analysis. Every claim about performance references the specific mechanism that enables it. Every DRY concern is resolved with a single-source-of-truth assignment.

---

### 1. Why Zig (not Rust, not Go, not C)

The kernel layer (`trustmesh-core/kernel/`) is written in Zig 0.15. This is not a novelty choice. Each Zig component in the propagation design maps to a specific Zig capability that the alternatives lack or make harder.

#### comptime: Compile-time code generation for keyword lists

`sensitivity.zig` declares `SENSITIVE_KEYWORDS` and `SENSITIVE_RELATIONSHIP_TYPES` as compile-time constant arrays:

```zig
const SENSITIVE_KEYWORDS = [_][]const u8{
    "medical", "health", "diagnosis", "prescription", ...
};
```

These are embedded in the binary at compile time. The `preflightSensitivity()` function iterates them with `for (SENSITIVE_KEYWORDS) |kw|` -- no heap allocation, no hash table construction, no runtime initialization. The compiler emits a flat scan over contiguous memory.

For propagation, `_infer_propagation()` in Zig (if we move keyword detection there) would use the same pattern: compile-time keyword lists for `broadcast`-tier triggers ("allerg", "medication", "emergency contact") checked against capsule metadata. The compiler can unroll these loops at `-Doptimize=ReleaseFast` because the iteration count is known at compile time.

**Rust comparison**: Rust's `const` arrays achieve similar embedding, but Zig's `comptime` goes further -- it allows arbitrary code execution at compile time, including string manipulation and pattern construction. A compile-time function can generate a perfect hash for keyword lookup. Rust's `const fn` is more restricted (no heap allocation, limited control flow until recent nightly features).

**Go comparison**: Go has no compile-time evaluation. The closest analog is `init()` functions that run at program start, which means the keyword set is constructed at runtime, allocated on the heap, and subject to GC pressure.

#### No hidden allocations / no GC: Critical for the transit engine

`transit.zig` is the vault key store. Keys are stored in a fixed-capacity array of `UserKeyRing` structs (`MAX_USERS = 256`). Each `KeySlot` contains a `[KEY_SIZE]u8` (32 bytes) key field. When a key is no longer needed, `secureZero()` calls `std.crypto.secureZero(u8, &self.key)`, which is guaranteed not to be optimized away by the compiler.

Why this matters for security:

1. **GC pause exposure**: In Go, a `[]byte` containing a key is subject to GC scanning. During a GC pause, the key bytes remain in memory longer than necessary, and the GC itself reads them during mark phase. The GC does not know that those bytes are sensitive. In Zig, `secureZero` runs at a deterministic time chosen by the programmer. There is no GC that might delay cleanup.

2. **No hidden copies**: Go's garbage collector can move objects during compaction (though current Go GC does not compact, this is an implementation detail, not a guarantee). Rust's ownership model prevents hidden copies but requires `unsafe` blocks and `Pin` for FFI-exposed types. Zig's value semantics and explicit allocation mean the key bytes exist at exactly one address, known at compile time (stack) or explicitly managed (heap via allocator).

3. **Allocator control**: `transit.zig` uses a page allocator for the keyring array. Python's `ctypes` bridge calls `podos_transit_store_key()` to copy key bytes into Zig memory, then the Python side can zero its copy. The Zig side controls exactly when those bytes are freed and zeroed. No allocator middleware, no GC finalizer, no destructor ordering ambiguity.

**C comparison**: C also offers manual memory management and no GC. But C has no `secureZero` equivalent in the standard library -- `memset` can be optimized away. Zig's `std.crypto.secureZero` uses volatile writes that the optimizer must preserve, per the Zig language specification.

#### C ABI exports: Python ctypes FFI with zero overhead

The kernel exposes C-callable functions via Zig's `export fn` mechanism:

```zig
export fn podos_transit_store_key(uid: [*]const u8, uid_len: c_int, key: [*]const u8) c_int { ... }
export fn podos_fts_search(db: *anyopaque, query: [*]const u8, ...) c_int { ... }
```

Python calls these via `ctypes.cdll.LoadLibrary("libpodos.dylib")`. The call overhead is a function pointer dereference -- the same cost as a C function call. There is no serialization boundary (no JSON, no protobuf, no IPC socket). The data crosses the boundary as raw pointers with explicit lengths.

**Rust comparison**: Rust requires `#[no_mangle] pub extern "C" fn` declarations and `unsafe` blocks for any pointer parameter. `cbindgen` generates C headers, but every function that touches Rust types must be wrapped in `unsafe`. Zig's C ABI export is a first-class language feature that does not require `unsafe` -- the caller-provided pointers are checked at the Zig boundary using slice bounds.

**Go comparison**: Go's `cgo` mechanism has measured overhead of 50-100ns per call (per the Go wiki and Dave Cheney's benchmarks from 2016, confirmed in Go 1.21 release notes as still relevant). For the transit engine, which is called on every capsule encrypt/decrypt, this overhead is significant at scale. Zig's FFI overhead is effectively zero -- it is a direct function call.

**C comparison**: C has the same zero-overhead FFI, but lacks safety. Buffer overruns in C are undefined behavior. In Zig, reading past a slice boundary is a detectable illegal behavior (safety-checked in Debug and ReleaseSafe modes). Production builds use `ReleaseFast` which elides these checks, matching C performance.

#### Packed structs / bit-level control: Debounce ring buffer and propagation targets

The proposed `propagation.zig` debounce buffer uses a ring buffer of fixed-size entries:

```
Entry: [36]u8 capsule_id + u8 propagation_level + i64 timestamp = 45 bytes
Ring buffer: [256]Entry = 11,520 bytes per pod destination
```

This fits in L1 cache (typically 32-64 KB on modern x86). Sequential iteration over the ring buffer to check for duplicates or flush expired entries benefits from hardware prefetching because the memory layout is contiguous and predictable.

Zig's `packed struct` and explicit byte-level layout control make this possible. The `[36]u8` capsule ID field is a fixed-width UUID string -- no heap pointer, no length field, no padding. The entire ring buffer is stack-allocated or embedded in a larger struct.

**Rust comparison**: Rust's `#[repr(C)]` and `#[repr(packed)]` achieve similar layout control, but require `unsafe` for unaligned access to packed fields. Zig's packed structs allow safe access with `@bitCast`.

**Go comparison**: Go's `struct` layout includes padding by default, and `unsafe.Sizeof` reveals the actual layout but cannot control it. There is no `packed` equivalent. A 45-byte entry in Go becomes 48 bytes after alignment padding, wasting 6.7% of cache space.

#### Error unions: No panics on the federated write path

Every Zig function in the kernel returns an error union (`TrustError!u32`, `FtsError!void`, etc.). The caller must explicitly handle or propagate every error. There is no exception unwinding, no hidden panic path, no `try!` macro that silently converts errors.

For the federated write path (`POST /api/pod/write`), this is a hard requirement. A remote pod can send arbitrary malformed payloads. If the handler panics on bad input, the entire Zig HTTP server process crashes. With error unions:

```zig
const role = roles.resolveRole(database, user_id, capsule_id) catch |err| {
    return ctx.sendError(403, "Forbidden");
};
```

The `catch` is not optional. The compiler rejects code that ignores an error union. This is structural prevention of crash-on-bad-input, not a testing discipline.

**Rust comparison**: Rust's `Result<T, E>` achieves the same mandatory error handling. However, Rust also has `panic!()` and `unwrap()` which are runtime aborts. Zig has `unreachable` (which is a safety-checked illegal behavior in safe modes), but the convention is stronger: the standard library does not use panics for recoverable errors, and there is no equivalent of `unwrap()` that silently converts errors to panics.

**Go comparison**: Go's `error` return values are not enforced by the compiler. A function returning `(int, error)` can have its error silently ignored: `val, _ := f()`. The `errcheck` linter catches some of these, but it is not part of the language specification.

**C comparison**: C has no error handling mechanism at all. Return codes are convention, not enforcement.

#### Cross-compilation: ARM64 Mac building x86_64 Linux containers

The kernel builds for Cloud Run (x86_64 Linux) from a macOS ARM64 development machine with a single flag:

```bash
zig build -Dtarget=x86_64-linux
```

This is not a cross-compilation toolchain. Zig bundles a complete C toolchain (libc headers, linker) for every supported target. The same `build.zig` that builds the native macOS `libpodos.dylib` also builds the Linux `libpodos.so` without installing any additional packages.

The `Dockerfile.backend` uses a two-stage build: the Zig compilation stage runs with `FROM --platform=$BUILDPLATFORM` (ARM64 on Apple Silicon) and cross-compiles to x86_64. The Python runtime stage uses `FROM python:3.12-slim` (x86_64). The SQLite amalgamation (`kernel/sqlite/sqlite3.c`) is compiled as part of the Zig build, ensuring the same FTS5 configuration on both platforms.

**Rust comparison**: Rust cross-compilation requires installing target-specific toolchains via `rustup target add x86_64-unknown-linux-gnu` and a C cross-compilation toolchain (e.g., `gcc-x86-64-linux-gnu` on macOS via Homebrew). This adds build dependencies and CI complexity.

**Go comparison**: Go has good cross-compilation support (`GOOS=linux GOARCH=amd64 go build`), but `cgo` (needed for SQLite) breaks this. Building Go with cgo for a different target requires a C cross-compiler, which is the same toolchain problem as Rust. Zig solves this because `zig cc` IS the cross-compiler.

---

### 2. Performance Benchmarks & Research References

#### AES-256-GCM throughput via hardware AES-NI

Zig's `std.crypto.aead.aes_gcm.Aes256Gcm` uses hardware AES-NI instructions when available (detected at compile time based on the target CPU features). `crypto.zig` calls `Aes256Gcm.encrypt()` directly.

**Benchmark reference**: Intel's "Intel Advanced Encryption Standard (AES) New Instructions Set" whitepaper (Shay Gueron, 2010, revised 2012) reports AES-256-GCM throughput of 4.15 cycles/byte on Westmere, improving to ~1 cycle/byte on subsequent architectures with PCLMULQDQ for GHASH. On a 3 GHz modern x86 processor, this translates to approximately 3-4 GB/s throughput for AES-256-GCM with hardware acceleration.

**TrustMesh application**: The transit engine encrypts/decrypts individual capsules (typically 0.5-5 KB). At 4 GB/s, a 5 KB capsule encrypts in ~1.25 microseconds. The re-encryption batch for role revocation (1000 capsules at 2 KB average = 2 MB) completes in ~0.5ms of pure crypto time. SQLite write I/O dominates at this scale.

**Constant-time guarantee**: Zig's AES-GCM implementation uses AES-NI hardware instructions, which are constant-time by design (the CPU executes the same microcode regardless of key or plaintext values). There are no key-dependent branches. This is relevant for the timing side-channel threat in Section 3.

#### SQLite FTS5 BM25 performance

The FTS5 extension in `fts.zig` uses BM25 ranking with porter stemming and unicode61 tokenization. The search query in `searchCapsules` uses `bm25(capsule_fts)` for ranking.

**Benchmark reference**: The SQLite FTS5 documentation (https://www.sqlite.org/fts5.html) states that BM25 ranking is computed incrementally during the query, with complexity proportional to O(D * T) where D is the number of matching documents and T is the number of query terms. The FTS5 inverted index uses a B-tree structure that supports logarithmic lookup per term.

**Measured expectations for TrustMesh**: With porter stemming and prefix indexes, typical query times on ARM64 (Apple Silicon M-series):
- 100 capsules, 4-term query: <2ms
- 1,000 capsules, 6-term query: <10ms
- 10,000 capsules, 6-term query: <60ms

The `json_each()` allowlist used for access control (`capsule_id IN (SELECT value FROM json_each(?))`) creates a temporary table. At 10,000+ accessible IDs, this temporary table creation dominates query time. The mitigation is category-scoped FTS5 search (Section 6, Optimization 1), which reduces the candidate set before the allowlist filter.

**Porter stemming interaction with staleness search**: When Peter's "dining preferences" capsule triggers a staleness search on Molly's pod, the query terms "peter dining preferences" are stemmed to "peter dine prefer". This matches Molly's itinerary containing "dining" (stemmed to "dine") but would NOT match "restaurant" (different stem). This is a known FTS5 limitation addressed by the semantic search upgrade path (Section 6).

#### Ed25519 signature verification

`federation_auth.zig` uses `std.crypto.sign.Ed25519` for federated request signing. Each `POST /api/pod/write` request includes an Ed25519 signature over the method, path, timestamp, nonce, and body.

**Benchmark reference**: The SUPERCOP benchmarking suite (https://bench.cr.yp.to/) reports Ed25519 verification at approximately 15,000-17,000 operations/second on modern x86_64 hardware (Intel Skylake and later). Bernstein et al., "High-speed high-security signatures" (Journal of Cryptographic Engineering, 2012) established the baseline at ~71,000 cycles for verification.

On a 3 GHz processor, 71,000 cycles = ~24 microseconds per verification, yielding ~42,000 verifications/second. In practice, with cache effects and context switching, 15,000/second is a conservative real-world number.

**TrustMesh application**: The federated write path does exactly 1 Ed25519 verification per request. Even under the stress case (200 concurrent write requests from 200 pods), this is 200 * 24 microseconds = 4.8ms of CPU time. Verification is not the bottleneck; SQLite write serialization is.

#### Fan-out-on-write vs fan-out-on-read: Twitter timeline architecture

**Reference**: Raffi Krikorian, "Timelines at Scale" (QCon 2012 / Twitter Engineering Blog, 2012). Twitter's architecture team documented their shift from pure fan-out-on-read (query all followees' tweets at read time) to fan-out-on-write (pre-compute timelines at tweet time), with a hybrid for high-follower accounts.

**Key finding**: Fan-out-on-write is optimal when:
1. Read:write ratio is high (>100:1)
2. Fan-out degree is bounded (not millions of followers)
3. Write latency tolerance is higher than read latency tolerance

TrustMesh matches all three criteria:
1. `query_peer` reads vastly outnumber capsule updates (users read 10-100x more than they write)
2. Network sizes are 5-50 members, bounded by real human social networks (Dunbar's number: ~150 for the entire social graph, ~5-15 for close trust networks)
3. Capsule updates can tolerate 5-second debounce windows; `query_peer` responses must be sub-second

The hybrid approach in this design (fan-out-on-write for `broadcast`, fan-out-on-write with debounce for `notify`, fan-out-on-read for `silent`) matches Twitter's recommendation for the shape of our access pattern.

#### Sliding window rate limiting

`rate_limit.zig` implements a `SlidingWindowCounter` using an in-memory hash map of event timestamps per key.

**Reference**: Google Cloud Architecture Center, "Rate-limiting strategies and techniques" (https://cloud.google.com/architecture/rate-limiting-strategies-techniques). Google documents four rate limiting patterns:
1. Token bucket (smooth rate + burst tolerance)
2. Leaky bucket (smooth rate, no burst)
3. Fixed window counter (simple, boundary burst problem)
4. Sliding window counter/log (accurate, higher memory)

TrustMesh uses pattern 4 (sliding window log). Each event is recorded with its timestamp. The `count()` function prunes events older than the window and returns the count of remaining events. Memory usage is O(events-in-window) per key.

**For propagation rate limiting**: The proposed max of 100 writes/minute per peer pod means the sliding window stores at most 100 timestamps (800 bytes) per peer pod URL. At 200 peer pods, total memory for rate limiting state is 200 * 800 = 160 KB. This fits comfortably in L2 cache.

---

### 3. Security Threat Model for Federated Writes

`POST /api/pod/write` is the most attack-sensitive endpoint in the propagation design. It allows a remote pod to modify data on the local pod. Every threat below is evaluated against the specific mitigations in the current architecture.

#### Threat 1: Privilege escalation via forged DID

**Attack**: Attacker pod sends a write request with `from_did: "did:key:z6Mk...admin_user"` claiming to be an admin of a capsule they have no authority over.

**Mitigation chain**:
1. Ed25519 signature verification (`federation_auth.zig`): The request includes a signature over the payload. The verifier extracts the public key from the DID (`did:key:z6Mk...` encodes the ed25519 public key with multicodec prefix `0xed01`). The signature must match the claimed DID's public key. An attacker cannot forge a signature without the private key.
2. Role resolution against LOCAL database (`roles.zig` / `trust.zig`): Even with a valid signature proving identity, the role check queries the LOCAL `capsule_roles` table. The attacker's claimed role is ignored. Role grants only exist because the capsule owner explicitly created them. A remote pod cannot INSERT into another pod's `capsule_roles` table.
3. Ghost user lookup: The DID must match a ghost user on the local pod. Ghost users are created during `pool-sync` (federation orchestration). An attacker cannot create ghost users on a pod they do not control.

**Residual risk**: If an attacker compromises the private key of a legitimate delegate (e.g., steals Dr. Lee's ed25519 private key), they can make write requests as Dr. Lee. Mitigation: key rotation via `POST /api/pod/rekey`, time-limited roles (`CapsuleRole.expires_at`), and audit logging of all write operations.

#### Threat 2: Replay attack

**Attack**: Attacker captures a valid `POST /api/pod/write` request (e.g., via network sniffing) and replays it to apply the same change again, or to apply an old change after the capsule has been updated.

**Mitigation**:
1. Timestamp window: `federation_auth.zig` sets `DEFAULT_SKEW_SECONDS = 60`. Requests with timestamps more than 60 seconds in the past are rejected. This limits the replay window to 60 seconds.
2. Nonce cache: Each request includes a random nonce (`X-TrustMesh-Nonce`). The receiving pod stores seen nonces in `_nonce_cache` with TTL of `DEFAULT_NONCE_TTL_SECONDS = 120`. A replayed request with the same nonce is rejected with `ReplayDetected`.
3. Version conflict: The write request can include `expected_version`. If the capsule version has advanced since the original request, the replay produces a 409 Conflict even if the nonce cache has been pruned.

**Residual risk**: Between the 0-60 second window and before the nonce is recorded, a high-speed replay on a separate network path could theoretically succeed. The version check serves as the final defense -- a replayed write to an already-updated capsule fails.

#### Threat 3: SSRF via pod_url

**Attack**: Attacker sends a write request with `from_pod: "http://169.254.169.254/latest/meta-data/"` or `from_pod: "http://10.0.0.1:6379/"` to probe internal services on the receiving pod's network.

**Mitigation**: `federation.py` implements `_validate_peer_url()`, which:
1. Parses the URL and extracts the hostname
2. Resolves the hostname to an IP address
3. Rejects private IP ranges: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16`, `::1`, `fc00::/7`
4. Rejects cloud metadata endpoints (matching `169.254.169.254` and `metadata.google.internal`)
5. When `TRUSTMESH_DEV_MODE=1`, these checks are skipped (development only; set in `tests/conftest.py`)

**Additional defense**: The write handler never makes outbound requests to `from_pod`. It only uses `from_pod` for logging and for the `propagation_origin` in cascade tracking. The DID is verified against the signature, not against a network call to `from_pod`.

#### Threat 4: Content injection (XSS, prompt injection)

**Attack**: Attacker with legitimate editor role injects malicious content into a capsule. The content could contain XSS payloads (for the UI) or prompt injection (for the LLM agent).

**Mitigation layers**:
1. **Encryption at rest**: Capsule content is stored as AES-256-GCM ciphertext. The injected content is encrypted like any other content. There is no special handling of "safe" vs "unsafe" content at the storage layer.
2. **Citadel security scanning**: On decryption (every read), the content passes through Citadel (`citadel.py`) which scans for prompt injection patterns, PII leakage, and other threats. Citadel uses ML-based detection (HuggingFace model) with a Python heuristic fallback.
3. **LLM agent defenses**: The agent system prompt in `agents.py` includes instruction boundaries and role-based content filtering. The agent does not execute arbitrary instructions from capsule content.
4. **Frontend sanitization**: The Next.js UI renders capsule content through React's JSX escaping, which prevents XSS by default. Raw HTML is never injected into the DOM.

**Residual risk**: A sophisticated prompt injection embedded in capsule content might influence agent behavior when the content is included in a query context. Citadel's heuristic fallback has known blind spots. The mitigation is defense in depth, not a single gate.

#### Threat 5: Key extraction via timing side-channel

**Attack**: Attacker sends many write requests with slightly varying content and measures response times to infer information about the vault key or the plaintext of other capsules.

**Mitigation**:
1. **AES-NI constant-time operations**: `crypto.zig` uses `std.crypto.aead.aes_gcm.Aes256Gcm`, which delegates to hardware AES-NI instructions on x86_64. AES-NI executes in constant time (same cycle count regardless of key or plaintext). There are no key-dependent table lookups (unlike software AES implementations vulnerable to cache-timing attacks as demonstrated by Bernstein, "Cache-timing attacks on AES," 2005).
2. **Ed25519 constant-time verification**: Zig's `std.crypto.sign.Ed25519` uses constant-time field arithmetic for signature verification. No branching on secret-dependent values.
3. **No timing information leakage from error paths**: Both the "capsule not found" and "access denied" error paths return the same HTTP status code (403 Forbidden) in the same response format. An attacker cannot distinguish "this capsule does not exist" from "you do not have access."

**Residual risk**: Network-level timing variations (TCP/TLS handshake jitter, kernel scheduling) can mask sub-microsecond crypto timing differences. The practical exploitability of timing side-channels over a network is very low for per-request operations (as argued by Crosby et al., "Opportunities and Limits of Remote Timing Attacks," ACM TISSEC, 2009).

#### Threat 6: Denial of service via write flood

**Attack**: A compromised or malicious pod sends thousands of write requests per second to overwhelm the receiving pod.

**Mitigation**:
1. **`rate_limit.zig` sliding window**: The proposed configuration limits write requests to 100/minute per source pod URL. This is enforced before JSON parsing, DID verification, or database access. Rejected requests return 429 immediately.
2. **Connection timeout**: The Zig HTTP server sets `SO_RCVTIMEO` to 30 seconds, preventing slowloris-style connection exhaustion.
3. **SQLite WAL serialization**: SQLite's write-ahead log serializes all writes. A flood of concurrent writes queues behind the WAL lock, bounded by SQLite's busy timeout. This naturally throttles write throughput to what the disk can sustain, without amplifying resource usage.

**Residual risk**: An attacker controlling many distinct pod URLs could bypass the per-pod rate limit. Defense: global rate limit across all sources (not yet implemented; should be added as `max_total_writes_per_minute`).

#### Threat 7: Ghost user impersonation

**Attack**: Attacker creates a ghost user on their own pod with `username: "admin"` and `display_name: "Rose Johnson"`, then sends a write request claiming to be Rose.

**Mitigation**: Ghost users on the attacker's pod are irrelevant. The write request goes to ROSE'S pod, where:
1. The DID in the request is verified against the signature (the attacker does not have Rose's private key)
2. Role resolution checks the LOCAL `capsule_roles` table on Rose's pod
3. The ghost user on the attacker's pod has no entries in Rose's `capsule_roles` table

**Key insight**: Ghost users are local identity placeholders. They have no authority on remote pods. Authority comes from `CapsuleRole` entries created by the capsule owner on the capsule's pod. A ghost user on pod A has zero influence on pod B's role table.

---

### 4. DRY Audit: Eliminating Duplication Between Zig and Python

The Zig kernel and Python intelligence layer intentionally overlap in some areas (both can query the same SQLite database). This section audits every overlap and assigns a single source of truth.

#### Trust resolution

- **Zig**: `trust.zig` -- `resolveTrustLevel()` executes a single SQL query joining `networks`, `network_memberships`, and `connections`. Returns JSON with trust level and network IDs. Zero SQLAlchemy overhead.
- **Python**: `trust.py` -- `resolve_trust_level()` first tries the Zig FFI path (`lib.podos_trust_resolve()`), then falls back to SQLAlchemy queries if the Zig DB handle is not available.

**Current state**: Python already delegates to Zig. The Python function is a thin FFI wrapper with a SQLAlchemy fallback for environments where the Zig library is not loaded (edge case in tests).

**Single source of truth: Zig.** Python calls via FFI. The SQLAlchemy fallback in Python exists only for graceful degradation when the Zig library fails to load. It is NOT an independent implementation -- it is a backup that should produce identical results. Any logic change must be made in `trust.zig` first.

#### Sensitivity detection

- **Zig**: `sensitivity.zig` -- `preflightSensitivity()` checks text against compile-time keyword lists and relationship types. Zero-allocation stack-based scan. Returns boolean.
- **Python**: `agents.py` -- `detect_sensitivity()` checks capsule categories, question content, and uses the `hint` parameter from Zig's pre-flight check.

**Current state**: These are NOT duplicates. They serve different purposes at different layers:
- Zig runs at the channel boundary (every inbound request, including NullClaw/ZeroClaw webhooks). It is a fast pre-filter that flags obviously sensitive content before any LLM processing.
- Python runs at the agent layer (only during agent reasoning). It considers capsule metadata (categories, types), the full question context, and the Zig hint as a floor. Python can detect sensitivity that requires understanding context ("Tell me about Rose's hospital visit" is sensitive even if no keyword matches).

**NOT a DRY violation -- they serve different purposes at different layers.** Zig is the hot-path pre-flight check. Python adds LLM-context-aware detection that Zig cannot do. The `hint` parameter ensures the Zig result flows forward: if Zig says "sensitive," Python cannot downgrade it.

#### Role resolution (new)

- **Zig**: Proposed `roles.zig` -- `podos_resolve_role()` executes a single SQL query with `LEFT JOIN` on `capsule_roles`, `network_memberships`, `sharing_delegates`. Returns the highest role as a `u8` enum (0=none, 1=viewer, 2=editor, 3=admin, 4=owner).
- **Python**: MUST NOT re-implement this query.

**Single source of truth: Zig.** Python calls `podos_resolve_role()` via FFI. The Python route handlers (`routes/capsules.py`) call the Zig function for authorization checks. If the Zig library is unavailable, the request fails with 503 -- role resolution is a security gate and must not silently degrade to an untested Python reimplementation.

#### Capsule CRUD

- **Zig**: `handlers/capsules.zig` handles standard CRUD operations in Zig HTTP mode (GET/POST/PUT/DELETE on `/api/users/{id}/capsules`).
- **Python**: `routes/capsules.py` handles capsule operations when Python is the primary HTTP server (no Zig HTTP mode).

**Current state**: In Zig HTTP mode (`TRUSTMESH_ZIG_HTTP=1`), Zig handles the request directly. Unmatched routes proxy to Python. In standard mode, Python handles everything and calls Zig for FTS5 indexing and encryption via FFI.

**NOT duplication -- they handle different deployment modes.** In Zig HTTP mode, Zig owns CRUD (hot path) and Python handles complex operations (version history with SQLAlchemy ORM objects, audit logging with Python datetime formatting, embedding updates via Voyage AI). In standard mode, Python owns CRUD and delegates storage-critical operations (encryption, FTS5) to Zig via FFI.

**Design principle**: Zig handles the standard CRUD hot path. Python handles operations that require ORM objects, external APIs, or complex business logic. The deployment mode determines which layer is the HTTP entry point, but the encryption and search always go through Zig.

#### Propagation target resolution (new)

- **Zig**: Proposed function in `trust.zig` -- `podos_propagation_targets()` executes a single SQL query joining `capsule_network_access`, `network_memberships`, and `users WHERE is_remote = 1`, grouped by `remote_pod_url`.
- **Python**: MUST NOT re-implement this query.

**Single source of truth: Zig.** Python calls the Zig function via FFI to get a list of `{pod_url, user_ids}` pairs. Python then uses `httpx` for the HTTP delivery. The SQL query lives in Zig because it runs on every capsule update with `propagation != "silent"`, making it a hot-path operation that benefits from Zig's prepared statement caching and zero-allocation result buffering.

#### Summary table

| Component | Single source of truth | Other layer's role |
|-----------|----------------------|-------------------|
| Trust resolution | **Zig** (`trust.zig`) | Python calls via FFI, has SQLAlchemy fallback for degraded mode |
| Sensitivity detection | **Both** (intentionally split) | Zig: hot-path pre-filter. Python: context-aware LLM-layer detection |
| Role resolution | **Zig** (`roles.zig`, new) | Python calls via FFI. No Python reimplementation. |
| Capsule CRUD | **Deployment-dependent** | Zig HTTP mode: Zig entry + Python complex ops. Standard mode: Python entry + Zig FFI for crypto/search. |
| Propagation target resolution | **Zig** (`trust.zig`, new) | Python calls via FFI for pod URL list. Python sends HTTP. |
| Propagation inference (`_infer_propagation`) | **Python** (`propagation.py`) | Zig does not implement this. NLP-like keyword matching needs iteration speed on pattern changes. |
| Agent hooks / LLM prompts | **Python** (`agents.py`) | Zig does not implement this. Prompt engineering changes too frequently for compiled code. |
| Federation HTTP delivery | **Python** (`httpx`) | Zig does not make outbound HTTP calls. Python handles retry, backoff, TLS. |

---

### 5. Scaling Principles Applied

Each design decision in the propagation system maps to a named scaling principle. These are not abstract -- each is grounded in the specific TrustMesh architecture.

#### Data locality: Capsules stay on the owner's pod

**Principle**: Data should be processed close to where it is stored. Cross-datacenter data movement is the largest source of latency in distributed systems (Jeff Dean's "Numbers Every Programmer Should Know": cross-datacenter round trip ~150ms vs intra-datacenter ~0.5ms).

**Application**: Peter's capsules live on Peter's pod. Molly cannot copy them to her pod. When propagation fires, the notification payload contains metadata (title, category, timestamp) but NOT the capsule content. The content stays on the source pod and is only decrypted when a `query_peer` request arrives.

**Consequence**: Staleness detection happens on the RECEIVING pod (Molly's) against Molly's LOCAL capsules. There is no cross-pod search. Molly's pod asks "which of MY capsules reference Peter?" -- a local FTS5 query against local data. This is O(K) where K is Molly's capsule count, not Peter's.

**What this eliminates**: No distributed FTS5 index. No cross-pod query federation for staleness. No data replication. No consistency protocol for replicated capsule content.

#### Fan-out budget: Debounce + batch bounds worst-case cost

**Principle**: Bound the work per write operation. In Twitter's terms: control the "fan-out cost" so that one user's action does not consume unbounded resources.

**Application**: The debounce buffer batches capsule updates within a 5-second window. After batching, the system sends ONE notification per destination pod, regardless of how many capsules changed. The fan-out cost is O(P) where P = distinct destination pods, not O(C * M) where C = capsules and M = members.

**Concrete bound**: In the stress case (10,000 capsules, 200 pods), batching reduces federation calls from 2,000,000 to 200. The per-write cost is amortized across all capsules in the batch window.

**The broadcast exception**: `broadcast`-level propagation bypasses debounce because it is safety-critical (allergies, medications). This is an intentional budget violation -- safety trumps efficiency. The assumption is that broadcast-level capsules are rare (< 5% of all capsules), so the budget is not materially affected.

#### Read-write asymmetry: Optimize the common path

**Principle**: In systems with asymmetric read:write ratios, optimize the frequent operation even at the cost of making the infrequent operation more expensive (Hellerstein, "Architecture of a Database System," 2007, Section 7.2 on workload-driven optimization).

**Application**: `query_peer` (reads) outnumber capsule updates (writes) by 10-100x in typical usage. The read path is optimized:
- Trust resolution via Zig: single SQL query, <1ms, prepared statement cached
- FTS5 search via Zig: in-process BM25, <10ms for typical pod sizes
- No propagation overhead on reads

The write path is more expensive:
- Encryption via Zig transit engine
- FTS5 index update
- Propagation target resolution (new SQL query)
- Debounce buffer management
- Eventual HTTP fan-out to peer pods

This asymmetry is correct. Writes happen when a user edits a capsule (minutes to hours between writes). Reads happen when agents query peers (potentially multiple times per user session).

#### Sovereignty as scaling advantage: No consensus protocol

**Principle**: If the data model allows single-writer semantics, avoid distributed consensus entirely. Consensus protocols (Raft, Paxos, PBFT) add latency, complexity, and failure modes proportional to the number of participants.

**Application**: Each capsule has exactly one owner pod. That pod is the single source of truth. There is no scenario where two pods both believe they own the same capsule. This eliminates:

- **CRDTs** (Conflict-free Replicated Data Types): Unnecessary. CRDTs solve concurrent writes to shared state. TrustMesh has no shared state -- each capsule is owned by exactly one pod. The only "conflict" is when multiple editors write to the same capsule, which is serialized by SQLite's WAL lock on the owner's pod.
- **Raft/Paxos**: Unnecessary. No distributed agreement is needed because there is no distributed state. Each pod makes unilateral decisions about its own capsules.
- **Eventual consistency reconciliation**: Unnecessary. Consistency is STRONG for each capsule because it has a single writer. The "eventual" aspect is only in notification delivery (Molly learns about Peter's change after a debounce window), which is a notification latency, not a data consistency issue.

**Comparison to ActivityPub/Mastodon**: ActivityPub uses a similar single-origin model (each post has one origin server), but ActivityPub replicates the CONTENT to receiving servers. TrustMesh does not replicate content -- only metadata notifications. This further simplifies consistency because there is nothing to reconcile.

**The scaling implication**: Adding a new pod to the network requires zero coordination with existing pods. The new pod registers with the registry (Layer 3), syncs network memberships with peer pods via `pool-sync`, and starts operating. No quorum, no leader election, no partition healing. Each pod is independently consistent.

#### Zero-copy where possible: Transit engine buffer management

**Principle**: Avoid intermediate copies of sensitive data. Each copy extends the time window during which sensitive bytes exist in memory, and increases the number of memory locations that must be securely zeroed.

**Application in `transit.zig`**:
1. `encrypt()` writes directly into a caller-provided output buffer (`out: []u8`). The plaintext is read once, the ciphertext is written once. No intermediate `ArrayList` or dynamic buffer.
2. `decrypt()` reads the ciphertext from the caller's buffer and writes plaintext into the caller's output buffer. The key bytes are read from the `KeySlot` in the keyring, which is the single authoritative copy.
3. After `encrypt()` returns, the caller's plaintext buffer can be zeroed immediately. After `decrypt()` returns, the ciphertext buffer can be released.

**Python-side discipline**: `transit_bridge.py` uses `ctypes.create_string_buffer()` for the output buffer, which is a mutable C-compatible array. After reading the decrypted result, the Python code should zero this buffer (though Python's garbage collector makes this best-effort, not guaranteed -- another argument for keeping crypto in Zig where zeroing IS guaranteed).

**Contrast with a JSON serialization boundary**: If the transit engine exposed an HTTP API (e.g., HashiCorp Vault style), every encrypt/decrypt would serialize the plaintext as JSON over an HTTP connection, creating at least 3 copies: the original buffer, the JSON string, and the HTTP response body. The ctypes FFI avoids all three.

---

## Scenario Modeling: Data Lifecycle from New Account to Scale

The architecture sections above describe the engine. This section traces HOW data actually flows through a user's lifecycle — what exists today, what needs building, what metrics tell us it's working, and where it breaks.

### Stage 1: New Account — Peter Signs Up

**What happens today (implemented):**
```
Peter opens http://localhost:3050 → selects "Your Pod :9000" → signs up
  → POST /api/users: creates User record, generates vault key (AES-256),
    encrypts with Argon2id-derived key, generates ed25519 keypair, creates Agent
  → POST /api/auth/login: session cookie set, vault key loaded into Zig transit engine
  → Redirect to /onboard: agent asks about Peter's life, saves capsules
```

Peter's pod has: 1 user, 1 agent, 0 connections, 0 networks, ~5-10 capsules from onboarding.

**Propagation at this stage:** Nothing to propagate. Peter has no connections. All capsules are `private` or `internal` with no networks to share to. `propagation` field defaults to `silent` on everything.

**What's missing:**
- Onboarding doesn't ask about propagation preferences yet
- No `default_propagation` on User model
- Agent doesn't clarify "should your family know when you update your diet?"

**Metrics to track:**
| Metric | Target | How to measure |
|--------|--------|----------------|
| Onboard completion rate | >80% of signups complete onboarding | `COUNT(capsules) >= 3 WHERE user.created_at > 7 days ago` |
| Capsules created in first session | 5-10 | `COUNT(capsules) WHERE created_at < user.created_at + 1 hour` |
| Time from signup to first capsule | <5 minutes | `MIN(capsule.created_at) - user.created_at` |

### Stage 2: First Connection — Peter Connects to Molly

**What happens today (implemented):**
```
Peter sends connection request to Molly
  → POST /api/connections/request (or agent calls send_connection_request tool)
  → Molly accepts → Connection record created (bidirectional)
  → Trust resolution: Peter ↔ Molly = "connected" trust level
  → Peter can now query_peer(molly) and see her open capsules
```

No networks yet. Just a direct connection. Trust = "connected" (sees `open` capsules only).

**Propagation at this stage:** Still nothing meaningful. Connected users can query each other but there's no shared network, so `internal` capsules are invisible. Peter updating his diet has no effect on Molly — she can't see it at "connected" trust.

**What this stage reveals:** The gap between "connected" and "network" trust is the first value unlock for propagation. Peter and Molly need a shared network before data sharing kicks in.

**What's missing:** Nothing for this stage — connections work today.

### Stage 3: First Network — The Johnsons Family Pool

**What happens today (implemented):**
```
Peter creates "The Johnsons" network (pool_type=standard)
  → POST /api/networks: Network record, Peter as owner
  → Invites Molly, Jane, Bill, Rose → NetworkMembership records
  → Each member's capsules with visibility=internal shared to "The Johnsons"
    become visible to other members via query_peer at trust="network"
```

Peter's pod now has: 1 user, 5 connections, 1 network with 5 members, ~15 capsules.

**Propagation at this stage:** THIS is where propagation becomes meaningful.
```
Peter updates "Travel & Dining Preferences" (shared to The Johnsons)
  → Without propagation: Molly finds out next time she queries Peter (could be days)
  → With propagation=notify: Molly gets a notification immediately
```

**What's missing (needs implementation):**
1. `propagation` field on capsule model — Phase 1
2. Notification fan-out to local network members — Phase 1
3. Agent clarification: "This is shared with The Johnsons. Notify them on changes?" — Phase 1
4. For multi-pod: cross-pod notification via `POST /api/pod/notify` — Phase 2

**Scale at this stage:**
- 1 network × 5 members = up to 5 notifications per capsule update
- Local-only (single pod): O(5) DB inserts = <1ms
- Multi-pod federation: O(4) HTTP calls to peer pods = ~60ms
- FTS5 staleness search: 15 capsules per member = <1ms
- Total propagation cost per update: <100ms. No optimization needed.

**Metrics:**
| Metric | Target | How to measure |
|--------|--------|----------------|
| Network creation rate | >50% of users with 2+ connections create a network | `COUNT(DISTINCT networks.owner_id) / COUNT(DISTINCT users.id WHERE connections >= 2)` |
| Capsules shared to networks | >30% of capsules have network_access | `COUNT(capsule_network_access) / COUNT(capsules)` |
| Cross-pod query success rate | >95% | `COUNT(queries WHERE decision='allowed') / COUNT(queries WHERE federated=true)` |

### Stage 4: Active User — Peter Has Multiple Networks

```
Peter's pod: 1 user, 12 connections, 4 networks:
  - The Johnsons (family, 5 members, standard pool)
  - Rose's Care Circle (health, 4 members, category_scoped)
  - Riverside Neighbors (friends, 3 members, standard)
  - Bay Area Music Lovers (public, 1 member, public_registry)

Capsules: ~50 (mix of private, internal, open)
  - 15 health capsules (internal, shared to Care Circle)
  - 10 family capsules (internal, shared to Johnsons)
  - 5 open capsules (discoverable by anyone)
  - 20 private capsules (journals, financial)
```

**Propagation at this stage:** Multiple networks mean a single capsule update can fan out to multiple groups.
```
Peter updates "Medical Info" (shared to Care Circle, propagation=broadcast)
  → Molly (Care Circle member on :9001) gets notification with change details
  → Dorothy (Care Circle member on :9008) gets notification
  → Rose (Care Circle member on :9004) gets notification
  → Jane (NOT in Care Circle) does NOT get notified — trust boundary enforced
```

**What needs to work:**
- Category-scoped propagation: health capsules only propagate to health-scoped networks
- Network deduplication: if Peter is in 2 networks with Molly, she gets 1 notification not 2
- Propagation mode per capsule: medical info = broadcast, music preferences = silent

**Scale:**
- 50 capsules × avg 1.5 networks each × avg 4 members = ~300 potential notifications
- With batching: 50 updates → 4 pods notified → 4 HTTP calls
- FTS5 staleness on each receiving pod: 50 capsules searched per notification = <5ms

**What's missing (Phase 2):**
- Cross-pod notification deduplication
- Category-scoped propagation filtering (don't propagate family capsule updates to health-scoped networks)
- Notification batching across capsule updates

### Stage 5: Orchestrator Role — Molly Plans a Trip

This is our demo scenario. Molly isn't just a passive consumer — she actively queries peers, aggregates data, and creates NEW capsules that reference others' data.

```
Molly's agent:
  1. query_peer(peter) → gets Peter's diet (vegetarian) from :9002
  2. query_peer(grandmarose) → gets Rose's dining prefs from :9004
  3. browse_web → TinyFish finds Michelin restaurants
  4. save_capsule → "San Sebastián 5-Day Itinerary" (internal, shared to Johnsons)
```

**The itinerary capsule creates a DEPENDENCY:**
- Itinerary references Peter's diet ("vegetarian restaurants")
- Itinerary references Rose's preferences ("no French/Italian")
- If either changes, the itinerary is STALE

**What's missing (Phase 3 — staleness detection):**
```
Peter updates diet → notification arrives on Molly's pod
  → Zig FTS5: search Molly's capsules for "peter" + "diet" + "vegetarian"
  → Finds: itinerary capsule mentions "Peter: vegetarian"
  → Mark stale → create timeline entry → agent re-triggers
```

**Scale:**
- Molly has ~50 capsules. Staleness search = <5ms.
- Agent re-trigger = 1 query_peer + possibly 1 browse_web = 15-90 seconds
- This is an infrequent operation (triggered by upstream changes, not every request)

**Metrics:**
| Metric | Target | How to measure |
|--------|--------|----------------|
| Staleness detection accuracy | >90% true positives | Manual review: did the flagged capsule actually reference stale data? |
| False positive rate | <20% | Flagged as stale but content didn't actually need updating |
| Re-trigger latency | <2 minutes from source update to itinerary updated | `itinerary.updated_at - source_capsule.updated_at` |
| Agent re-query success | >95% | `query_peer` succeeds on re-trigger |

### Stage 6: Growth — 100+ Capsules, 20+ Connections

```
Peter's pod after 6 months:
  100 capsules, 20 connections, 6 networks, 3 sharing delegates

  Networks span 12 distinct pods (multi-pod federation)
  Some capsules shared to 3+ networks simultaneously
  5 capsules have propagation=broadcast (health/emergency)
  20 capsules have propagation=notify (family/work)
  75 capsules are silent (personal, financial, general)
```

**What starts to matter:**
1. **Batching is mandatory** — without it, updating 5 health capsules in a row sends 5 × 12 = 60 HTTP calls. With batching: 5 updates in 5-second window → 12 HTTP calls (one per pod).
2. **Bloom filter helps** — of 12 peer pods, maybe only 4 have members in the health-scoped Care Circle. Bloom filter on pod → "does this pod have ANY members in network X?" eliminates 8 unnecessary calls.
3. **FTS5 needs category scoping** — searching 100 capsules for staleness after every notification is wasteful. Category-scoped search: "only search Molly's family capsules when a family capsule update arrives."

**What needs to be built (Phase 4):**
- `propagation.zig` debounce buffer — Zig ring buffer with 5-second timer
- Bloom filter for pod-level network membership — Zig `std.hash_map` based
- Category-scoped staleness search — FTS5 WHERE category IN (...)

**Metrics:**
| Metric | Target | How to measure |
|--------|--------|----------------|
| Propagation latency (p50) | <500ms | `notification.created_at - capsule.updated_at` on receiving pod |
| Propagation latency (p99) | <5s | Same, 99th percentile |
| HTTP calls per batch | O(P) not O(C×M) | `COUNT(federation_http_calls) / COUNT(capsule_updates_in_window)` |
| FTS5 staleness query time | <10ms p99 | Zig-side timing in `fts.zig` |
| Unnecessary notifications (Bloom filter savings) | >30% eliminated | `1 - (actual_http_calls / (pod_count × batch_count))` |

### Stage 7: Power User — Delegate, Admin, Multi-Role

```
Molly's pod:
  She's owner of 80 capsules
  She's admin of Rose's Care Circle (can manage membership)
  She's editor of Rose's medication capsule (via SharingDelegate)
  She's editor of the family vacation capsule (via CapsuleRole)
  She has 3 sharing delegates: Peter (family), Dr. Lee (health), Kyle (work)
```

**Write path complexity:**
```
Dr. Lee updates Rose's medication list from :9005
  → POST /api/pod/write to Rose's pod :9004
  → Zig: verify DID → resolve role (editor via SharingDelegate) → authorize
  → Zig: decrypt capsule → apply update → re-encrypt → save
  → capsule.propagation = broadcast
  → Zig: resolve targets → Care Circle members on pods :9001, :9002, :9008
  → Python: send notifications to 3 pods
  → Molly receives notification → staleness check → finds care routine references meds
  → Timeline trigger → agent re-queries Rose's pod for current meds → updates care routine
```

**What needs to be built (Phase 5):**
- `POST /api/pod/write` endpoint with full Zig authorization pipeline
- `roles.zig` with `podos_resolve_role()` supporting CapsuleRole + SharingDelegate + NetworkMembership
- Version conflict detection (`expected_version` check)
- Audit logging for all federated writes

**Conflict scenario at this stage:**
```
Dr. Lee updates meds at T=100 (via federated write to :9004)
Molly updates care routine at T=100.5 (via federated write to :9004)

SQLite serializes on :9004:
  T=100:   Dr. Lee → meds capsule → version 7 (no conflict, different capsule)
  T=100.5: Molly → care routine → version 12 (no conflict, different capsule)

BUT: if both edit the SAME capsule (meds):
  T=100:   Dr. Lee → meds → version 7 ✓
  T=100.5: Molly → meds → expected_version=6 → CONFLICT (version is now 7)
  → Molly gets 409: "Dr. Lee updated this 0.5s ago. Fetch current version first."
```

**Metrics:**
| Metric | Target | How to measure |
|--------|--------|----------------|
| Federated write success rate | >99% | `COUNT(pod_write WHERE status=200) / COUNT(pod_write)` |
| Role resolution latency | <1ms | Zig-side timing in `roles.zig` |
| Version conflict rate | <5% | `COUNT(pod_write WHERE status=409) / COUNT(pod_write)` |
| Re-encryption time (admin removal) | <100ms for 100 capsules | Zig-side timing in `transit.zig` `podos_rekey_capsules()` |
| Audit coverage | 100% of writes logged | `COUNT(audit_logs WHERE action='pod_write') == COUNT(pod_write WHERE status=200)` |

### Stage 8: Scale — What Breaks at 10,000 Users

Not 10,000 on one pod — 10,000 pods in the federation. Each pod has 1 user, ~100 capsules, ~20 connections spanning ~50 distinct pods.

```
Global state:
  10,000 pods × 100 capsules = 1M capsules total
  10,000 pods × 20 connections = 200K connections
  ~5,000 networks spanning ~3 pods each on average

  Worst case: a "company" network with 500 members across 200 pods
```

**What breaks:**

| Problem | Where it breaks | Solution |
|---------|----------------|----------|
| Notification fan-out to 200 pods | 200 HTTP calls per capsule update (even with batching) | Tiered delivery: priority pods first (active members), background for inactive. Pub/sub for >100 pods. |
| FTS5 on 100 capsules is fast, but 10K concurrent staleness searches | SQLite write contention on receiving pods | Read-only FTS5 queries don't contend with writes in WAL mode. But 10K simultaneous notifications arriving = 10K FTS5 queries. Solution: notification queue with rate limiting on the receiver side. |
| Bloom filter memory | 10,000 pod URLs × bloom filter state | Bloom filter is per-network, not per-pod. 5,000 networks × 128 bytes = 640KB. Fine. |
| Registry becomes bottleneck | 10,000 agents registered, discovery queries slow | Shard registry by region. Or: pod-to-pod discovery via gossip protocol, bypass registry. |
| Re-encryption at scale | Company admin removed from 500-member network, 500 pods need re-keying | Re-key is per-pod (each pod re-encrypts its own capsules). No cross-pod coordination. 500 pods independently re-key = embarrassingly parallel. |

**What we DON'T need (and why):**
- **No distributed database**: each pod is sovereign. No Spanner, no CockroachDB, no DynamoDB.
- **No consensus protocol**: no Raft, no Paxos. Each capsule has exactly one owner pod. No split-brain possible.
- **No CRDTs**: no conflict-free replicated data types. We have last-write-wins + version alerting. CRDTs add complexity for a problem we don't have (multiple writable replicas).
- **No message queue (at current scale)**: HTTP POST for notifications. At >1000 pods per network, add a pub/sub layer (NATS, Redis Streams). But personal AI agents rarely have 1000-member networks.

### Implementation Roadmap

| Phase | What to build | Stage unlocked | Estimated effort |
|-------|--------------|----------------|-----------------|
| **Phase 1** | `propagation` field, local notification fan-out, CLI `--propagation` flag, agent clarification prompt | Stage 3 (first network) | 2-3 days |
| **Phase 2** | `POST /api/pod/notify`, cross-pod notification delivery, batching, deduplication | Stage 4 (multi-network) | 3-5 days |
| **Phase 3** | Staleness detection (FTS5 search on notification receipt), timeline auto-trigger, agent hook_prompt | Stage 5 (orchestrator) | 3-5 days |
| **Phase 4** | `propagation.zig` debounce buffer, Bloom filter, category-scoped staleness | Stage 6 (growth) | 5-7 days |
| **Phase 5** | `POST /api/pod/write`, `roles.zig`, CapsuleRole model, version conflict, re-encryption, audit | Stage 7 (power user) | 7-10 days |
| **Phase 6** | Tiered delivery, notification queuing, receiver-side rate limiting, registry sharding | Stage 8 (scale) | 10-15 days |

### Evaluation Framework

How do we know each phase is working?

**Phase 1 evaluation:**
```
Test: Peter updates a capsule with propagation=notify, shared to The Johnsons
Assert: Molly, Jane, Bill each have a Notification record within 1 second
Assert: Peter does NOT have a self-notification
Assert: Rose (not in The Johnsons at this test point) does NOT have a notification
Measure: notification_count == expected_member_count - 1 (exclude owner)
```

**Phase 2 evaluation:**
```
Test: Peter (pod :9002) updates capsule. Molly is on :9001, Rose on :9004.
Assert: POST /api/pod/notify sent to :9001 and :9004 (not to :9002)
Assert: Molly's pod creates local Notification for molly
Assert: Rose's pod creates local Notification for grandmarose
Measure: HTTP calls == distinct_peer_pod_count (2, not member_count)
```

**Phase 3 evaluation:**
```
Test: Molly has itinerary referencing "Peter: vegetarian". Peter changes to pescatarian.
Assert: Notification arrives on Molly's pod
Assert: FTS5 search finds the itinerary capsule
Assert: Timeline entry created with hook_prompt mentioning "pescatarian"
Assert: Agent re-queries Peter → gets "pescatarian" → updates itinerary
Measure: time_from_peter_update_to_itinerary_update < 120 seconds
```

**Phase 5 evaluation:**
```
Test: Dr. Lee sends POST /api/pod/write to update Rose's meds on :9004
Assert: DID signature verified
Assert: Role resolved as "editor" via SharingDelegate
Assert: Capsule updated, version incremented
Assert: Propagation fires to Care Circle members
Assert: Audit log records the write with actor=dr_lee
Test: Dr. Lee tries to delete the capsule → 403 (editor can't delete)
Test: Replay the same write request → 409 (nonce already seen)
```

**Ongoing monitoring (production):**
| Metric | Alert threshold | Dashboard |
|--------|----------------|-----------|
| Propagation latency p99 | >10s | Grafana: `histogram(notification_latency_ms)` |
| Federation write failure rate | >5% | `rate(pod_write_errors) / rate(pod_write_total)` |
| Stale capsule detection rate | trending down over time | `count(capsules WHERE stale_since IS NOT NULL)` |
| FTS5 query latency p99 | >50ms | Zig-side counter exposed via `/health/full` |
| Notification queue depth (Phase 6) | >1000 pending | NATS/Redis queue metrics |
| Re-encryption duration | >1s for any single operation | Zig-side timer on `podos_rekey_capsules()` |

---

## Open Questions

1. **Voice input latency**: Speech-to-text → agent → save → propagation — acceptable latency for real-time feel? Target: <2s from speech end to notification sent.
2. **Registry-assisted discovery propagation**: If Peter joins a new public network, should existing members get notified? Layer 3 → Layer 2 bridge.
3. **Offline pods**: Notification queuing + retry strategy for unreachable pods.
4. **Cross-registry federation**: Multiple registries spanning organizations. Out of scope for v1.
5. **Encryption of notifications**: Notification metadata in transit vs at-rest.
6. **Role inheritance**: If Molly is admin of "The Johnsons" network, is she automatically admin of ALL capsules shared to that network, or just the network membership itself?
7. **Delegation chains**: Can an admin grant admin to someone else? Recommended: no — only owner grants admin. Admins can grant editor only.
8. **Audit trail for role changes**: Every grant/revoke should be logged. Use existing `audit_logs` table with `event_type="role_changed"`.
9. **Time-limited roles**: "Dr. Lee is editor of Rose's meds for 48 hours during this hospital visit." `CapsuleRole.expires_at` field?
10. **Bulk re-encryption cost**: If a network has 500 capsules and an admin is removed, re-encrypting 500 capsules costs ~5ms crypto + ~500ms SQLite writes. Acceptable? Should it be async/background?
