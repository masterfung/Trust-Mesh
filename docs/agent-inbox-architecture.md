# Agent Inbox Architecture

## Problem

Agents currently receive queries synchronously (someone asks, agent responds). But agents need an **asynchronous layer** for:
- Connection requests that need owner approval
- Network invitations
- Capsule freshness alerts ("this medication info is 90 days old")
- Dedup suggestions ("5 capsules about grandma's meds — merge?")
- Cross-agent notifications ("Molly updated the care routine")

Without an inbox, all these get dumped into one context, causing contamination. A friend request shouldn't mix with a medical procedure update.

## Three-Channel Inbox

```
Agent Inbox
├── PUBLIC channel (friend requests, discovery)
│   ├── Connection requests from strangers
│   ├── Profile view notifications
│   └── Public capsule access logs
│
├── INTERNAL channel (network activity)
│   ├── Query results from/to network members
│   ├── Network invitations
│   ├── Capsule shared-to-network notifications
│   ├── Cross-agent updates ("Molly updated care routine")
│   └── Network membership changes
│
└── PRIVATE channel (personal agent tasks)
    ├── Capsule freshness reviews ("verify this is still current?")
    ├── Dedup suggestions ("merge these 3 capsules?")
    ├── Data conflict alerts ("you said vegetarian but also pescatarian")
    ├── Auto-archive notifications
    └── Agent insights ("you haven't updated your schedule in 30 days")
```

## Data Model

```python
class InboxMessage:
    id: uuid
    agent_id: uuid            # Owner's agent
    channel: "public" | "internal" | "private"
    message_type: str         # "connection_request", "capsule_update", "freshness_review", etc.
    priority: "low" | "normal" | "high" | "urgent"

    # Content
    title: str                # "New connection request from Kyle Rivera"
    body: str                 # Details
    metadata: json            # Structured data (capsule_id, user_id, etc.)

    # State
    status: "unread" | "read" | "acted" | "dismissed"
    requires_action: bool     # True if human must decide (e.g., approve connection)
    auto_actionable: bool     # True if agent can handle without human

    # Timing
    created_at: datetime
    expires_at: datetime | None  # Some notifications are time-sensitive
    acted_at: datetime | None

class InboxChannel:
    agent_id: uuid
    channel: str
    unread_count: int
    last_message_at: datetime
```

## Message Types by Channel

### PUBLIC
| Type | Priority | Requires Action | Auto-Actionable |
|------|----------|-----------------|-----------------|
| `connection_request` | normal | yes | no (human approves) |
| `profile_viewed` | low | no | no |
| `public_query_received` | low | no | yes (agent responds) |

### INTERNAL
| Type | Priority | Requires Action | Auto-Actionable |
|------|----------|-----------------|-----------------|
| `network_invitation` | normal | yes | no (human accepts) |
| `capsule_shared` | low | no | no |
| `capsule_updated` | normal | no | yes (agent re-embeds) |
| `member_added` | low | no | no |
| `member_removed` | normal | no | yes (revoke access) |
| `query_received` | normal | no | yes (agent responds) |

### PRIVATE
| Type | Priority | Requires Action | Auto-Actionable |
|------|----------|-----------------|-----------------|
| `freshness_review` | normal | yes | no (human verifies) |
| `dedup_suggestion` | low | yes | partially (agent suggests, human confirms) |
| `data_conflict` | high | yes | no (human resolves) |
| `auto_archived` | low | no | no |
| `schema_update` | normal | yes | no (human confirms field change) |
| `capsule_expired` | normal | no | yes (agent archives) |

## Agent Processing Rules

```
When agent receives a query:
  1. Check channel — only process from appropriate context
  2. PUBLIC queries: only use public capsules, never leak internal/private
  3. INTERNAL queries: use public + shared-network capsules
  4. PRIVATE queries (self): use all capsules

When agent processes inbox:
  1. Auto-actionable items: handle immediately (re-embed, archive expired)
  2. Requires-action items: queue for human in UI
  3. Never mix channel contexts in LLM calls
     - Don't mention connection requests when answering medical questions
     - Don't reference private dedup suggestions in network responses
```

## Context Isolation

The key insight: **each channel gets its own LLM context window**. When the agent processes a public query, it never sees private inbox items. This prevents:

- Data leakage: private dedup suggestions mentioning capsule content
- Confusion: agent mixing friend request info with medical procedures
- Prompt injection across channels: attacker can't influence private channel via public query

```
Public Query Context:
  System prompt (public-safe version)
  + Public capsules only
  + Public channel inbox state (for context: "I have a pending connection request from you")

Network Query Context:
  System prompt (network version)
  + Public + network capsules
  + Internal channel state (for context: "Molly recently updated this info")

Private Query Context (self-query):
  System prompt (full access)
  + All capsules
  + All inbox channels
  + Dedup suggestions, freshness alerts, conflicts
```

## UI Integration

Dashboard sidebar shows inbox with channel badges:
```
📬 Inbox
  🌐 Public (2)        — connection requests
  👥 Internal (5)      — network activity
  🔒 Private (3)       — capsule management
```

Each channel opens a filtered view. Human can:
- Approve/decline connection requests (public)
- Accept network invitations (internal)
- Confirm freshness reviews (private)
- Approve dedup merges (private)
- Resolve data conflicts (private)

## Hackathon Scope

**Build for demo:**
- Connection request notifications in PUBLIC channel (already exist as ConnectionRequest model)
- Basic notification model + API endpoints

**Document as architecture:**
- Full three-channel system
- Auto-actionable processing
- Context isolation pattern
- Agent processing rules
