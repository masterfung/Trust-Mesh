# PodOS: The Timeline-Driven Operating System for Agents and Humans

> A pod is not an app. It's a computer. The timeline is not a calendar. It's the process model.

---

## The Problem With Today's Agent Architecture

Every agent system today — TrustMesh included — has the same structural flaw: **agents are reactive**. They sit in a loop waiting for a human to type something. Between interactions, they don't exist. They have no sense of time passing, no awareness that a deadline is approaching, no ability to notice that two things they know about are about to collide.

This isn't a missing feature. It's a missing **layer**.

Calendars don't solve it. A calendar is a display format — it renders time slots for human eyes. It has no concept of state activation, no lifecycle hooks, no dependency chains, no concept of "when this finishes, start that." Cron doesn't solve it either — cron fires commands at times, but has no awareness of what those commands mean, whether their prerequisites are met, or how they relate to each other.

What we need is a **temporal execution engine** — something that understands time, state, dependencies, and lifecycle as first-class primitives. Something that both humans and AI agents can operate within as a unified stream. Something that makes proactivity structural rather than bolted on.

This document describes that system: **PodOS**, with the **Timeline** as its core execution model.

---

## The Core Thesis

**A pod should function like a personal computer at the OS level.**

Not an app. Not a service. An operating system — with its own process model, scheduler, file system, IPC, permissions, and networking. The difference from a traditional OS:

| Traditional OS | PodOS | Why |
|---|---|---|
| Files | Capsules + External refs | Knowledge is encrypted, trust-scoped, and typed — not flat bytes |
| Processes | Timeline entries | The unit of execution is a stateful pointer with lifecycle, not running code |
| Process scheduler | Timeline engine (tick loop) | Evaluates triggers, manages state transitions, fires hooks |
| Syscalls | Pod API | How agents and humans manipulate timeline, vault, trust |
| User space | Agent reasoning + Human UI | Both operate on the same substrate, different lenses |
| Kernel | Pod Core | Manages state, dispatching, syncing, coordination |
| Network stack | Federation layer | Pod-to-pod, pool sync, registry |
| Permissions | Trust levels | private/internal/open per entry, inherited from owner |
| IPC / Signals | Events + hooks + dependency graph | Entries communicate through triggers and state changes |
| Mount points | Integration adapters | External systems (email, SaaS, storage) mounted into the timeline |
| Virtual memory | Reference resolution | `capsule://X` → decrypted content, without knowing the encryption details |

The timeline is not a feature on top of this OS. **The timeline IS the process model.** Every meaningful thing the pod tracks — an event, an idea, a task, a data reference, a hook, a dependency — is a timeline entry with a lifecycle. The pod's job is to advance time, evaluate those lifecycles, and coordinate the results.

---

## Architecture Layers

```
┌──────────────────────────────────────────────────────────────┐
│  LAYER 4: INTERFACE                                          │
│                                                              │
│  Human UI          Agent Interface       CLI / MCP           │
│  (calendar view,   (natural language,    (programmatic       │
│   dashboard,        tool calls,           access)            │
│   notifications)    reasoning)                               │
├──────────────────────────────────────────────────────────────┤
│  LAYER 3: SERVICES                                           │
│                                                              │
│  Agent Runtime    Integration     Notification    Search     │
│  (LLM reasoning,  Adapters       Service         Index      │
│   tool execution)  (email, SaaS,  (push to human, (semantic  │
│                    storage mounts) webhook out)    + temporal)│
├──────────────────────────────────────────────────────────────┤
│  LAYER 2: KERNEL (Pod Core)                                  │
│                                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────┐    │
│  │   Timeline    │ │    Vault     │ │   Trust Enforcer  │    │
│  │   Engine      │ │   Manager    │ │                   │    │
│  │              │ │              │ │  Visibility rules  │    │
│  │  Tick loop    │ │  Encrypt/    │ │  Access control    │    │
│  │  State machine│ │  Decrypt     │ │  Scope resolution  │    │
│  │  Trigger eval │ │  Capsule CRUD│ │  Trust inheritance │    │
│  │  Hook dispatch│ │  Ref resolve │ │                   │    │
│  └──────┬───────┘ └──────────────┘ └───────────────────┘    │
│         │                                                    │
│  ┌──────┴───────┐ ┌──────────────┐ ┌───────────────────┐    │
│  │  Dependency   │ │  Event Bus   │ │   Sync Engine     │    │
│  │  Graph        │ │              │ │                   │    │
│  │              │ │  Internal     │ │  Federation        │    │
│  │  DAG eval     │ │  External    │ │  Pool sync         │    │
│  │  Topo sort    │ │  Cross-pod   │ │  State reconcile   │    │
│  │  Cycle detect │ │  Buffered    │ │  Conflict resolve  │    │
│  └──────────────┘ └──────────────┘ └───────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│  LAYER 1: RUNTIME                                            │
│                                                              │
│  SQLite (state)  │ ChromaDB (vectors)  │  Filesystem (blobs)│
│  Clock source    │ Event queue          │  Network I/O       │
├──────────────────────────────────────────────────────────────┤
│  LAYER 0: HOST                                               │
│                                                              │
│  Laptop / Phone / Raspberry Pi / Cloud VM / Edge Device      │
└──────────────────────────────────────────────────────────────┘
```

---

## Layer 2 Deep Dive: The Kernel

### The Timeline Engine

The timeline engine is the **scheduler** of PodOS. It advances time, evaluates triggers, transitions entry states, fires hooks, recomputes central state, and dispatches work to the agent and integration layers.

#### The Tick Loop

```
┌─────────────────────────────────────────────┐
│              TICK (every interval)           │
│                                             │
│  1. ADVANCE CLOCK                           │
│     Read wall clock. Compute delta since    │
│     last tick.                              │
│                                             │
│  2. EVALUATE TIME TRIGGERS                  │
│     For all entries with time-based         │
│     activation/deactivation: compare        │
│     anchor/window against current time.     │
│     → Transition matching entries.          │
│                                             │
│  3. DRAIN EVENT QUEUE                       │
│     Process events that arrived since last  │
│     tick (email received, SaaS webhook,     │
│     capsule updated, peer message).         │
│     → Match events to entry triggers.       │
│     → Transition matching entries.          │
│                                             │
│  4. EVALUATE DEPENDENCY GRAPH               │
│     For all entries in PENDING state:       │
│     check if prerequisites are satisfied.   │
│     → Transition entries whose deps are met.│
│                                             │
│  5. EVALUATE CONDITIONS                     │
│     For entries with condition triggers:    │
│     evaluate predicates against current     │
│     state.                                  │
│     → Transition matching entries.          │
│                                             │
│  6. FIRE HOOKS                              │
│     For all entries that transitioned this  │
│     tick: fire pre/post hooks in order.     │
│     → Dispatch to agent, integrations, or   │
│       other entries.                        │
│                                             │
│  7. RECOMPUTE CENTRAL STATE                 │
│     Aggregate all active entries into the   │
│     pod's current state snapshot.           │
│     Compute attention signals.              │
│     → Push state delta to subscribers       │
│       (agent, UI, sync engine).             │
│                                             │
│  8. SYNC                                    │
│     Push outbound state changes to peers,   │
│     pools, shared timelines.                │
│     Pull inbound changes, feed back into    │
│     event queue for next tick.              │
│                                             │
│  9. SLEEP UNTIL NEXT TICK                   │
│     Or until woken by urgent event.         │
└─────────────────────────────────────────────┘
```

#### Tick Frequency is Adaptive

A naive "every second" tick is wasteful. The engine should be **event-driven with a heartbeat floor**:

- **Heartbeat**: tick runs at minimum every N seconds (configurable, say 60s) even if nothing happened. Catches time-based triggers that fall between events.
- **Event-woken**: any incoming event (email, webhook, user action, peer message) wakes the engine immediately for an out-of-cycle tick.
- **Pre-computed wake time**: the engine knows when the next time-based trigger fires and sets an alarm for exactly that moment. Between alarms and events, it sleeps.

This means a quiet pod with nothing pending uses near-zero CPU. A busy pod with many active entries and incoming events ticks frequently. The engine scales with load.

```
Quiet pod:    ──────────60s──────────60s──────────60s──────────
Active pod:   ──event─┬─event─┬─30s─┬─event─event─┬─45s──────
              (woken) (woken) (hb)  (woken×2)      (hb)
```

---

### The Timeline Entry: The Fundamental Primitive

A timeline entry is the **process** of PodOS. It's not data — it's a pointer to data, wrapped in a lifecycle state machine with triggers, hooks, dependencies, and visibility rules.

#### Entry Structure

```
TimelineEntry {
  // Identity
  id: UUID
  timeline_id: UUID         // which timeline this belongs to
  creator_id: UUID          // who/what created it (human, agent, integration, peer)

  // Reference — what this entry points to
  ref: {
    type: "capsule" | "saas" | "storage" | "pool" | "timeline"
          | "url" | "webhook" | "compute" | "null"
    uri: string             // "capsule://abc-123", "saas://gcal/event/xyz",
                            // "s3://bucket/key", "pool://techcorp-team",
                            // "timeline://branch-42/entry-99"
    cache_policy: "none" | "on_activate" | "always"
    resolved_snapshot: blob? // cached resolved data (encrypted at rest)
  }

  // Lifecycle State
  state: "dormant" | "pending" | "activating" | "active"
         | "deactivating" | "completed" | "failed" | "archived" | "deleted"

  // Time Binding (all optional — an entry can be unanchored)
  anchor: datetime?          // exact moment (like a calendar event)
  window: {                  // time range
    start: datetime?,
    end: datetime?
  }
  horizon: string?           // relative/fuzzy: "3d", "this_week", "Q2", "someday"

  // Activation Triggers — what causes dormant → pending → active
  activation: {
    type: "time" | "event" | "condition" | "dependency" | "manual"
    config: TriggerConfig    // type-specific (see Trigger Types below)
    pre_hooks: [Hook]        // fire BEFORE activation completes
  }

  // Deactivation Triggers — what causes active → deactivating → completed/archived
  deactivation: {
    type: "time" | "event" | "condition" | "manual" | "ttl"
    config: TriggerConfig
    post_hooks: [Hook]       // fire AFTER deactivation completes
  }

  // Dependencies — prerequisites that must be satisfied
  depends_on: [{
    entry_id: UUID,
    required_state: "active" | "completed"  // must this dep be active, or finished?
  }]

  // Visibility — who can see this entry
  visibility: "private" | "internal" | "open"
  visibility_scopes: [scope_id]?  // specific pools/connections if not blanket

  // Classification
  entry_type: "event" | "idea" | "data" | "reminder" | "hook" | "milestone"
              | "task" | "signal" | "mount" | "computed"
  category: string?          // "work", "health", "family", etc.
  tags: [string]
  salience: float (0.0-1.0)  // how important is this right now

  // Metadata
  created_at: datetime
  last_transition_at: datetime
  transition_history: [{state, timestamp, trigger}]  // audit trail

  // Branch context
  branch_id: UUID?           // if on a branch, which one
  main_shadow_id: UUID?      // if this shadows a main timeline entry
}
```

#### Entry Lifecycle State Machine

```
                          manual
                            │
                     ┌──────▼──────┐
          ┌──────────│   DORMANT    │
          │          │              │
          │          │ Entry exists │
          │          │ but is not   │
          │          │ yet relevant │
          │          └──────┬──────┘
          │                 │ trigger fires OR dependencies met
          │          ┌──────▼──────┐
          │          │   PENDING    │
          │          │              │
          │          │ Trigger fired│
          │          │ checking deps│
          │          └──────┬──────┘
          │                 │ all deps satisfied
          │          ┌──────▼──────┐
          │          │  ACTIVATING  │──── pre_hooks fire here
          │          │              │
          │          │ Refs being   │
          │          │ resolved,    │
          │          │ hooks firing │
          │          └──────┬──────┘
          │                 │ pre_hooks complete
          │          ┌──────▼──────┐
          │          │   ACTIVE     │
          │          │              │
          │          │ Entry is live│
          │          │ Agent sees it│
          │          │ Refs resolved│
          │          └──────┬──────┘
          │                 │ deactivation trigger fires
          │          ┌──────▼──────┐
          │          │ DEACTIVATING │──── post_hooks fire here
          │          │              │
          │          │ Cleaning up, │
          │          │ hooks firing │
          │          └──────┬──────┘
          │                 │
          │          ┌──────▼──────┐           ┌──────────┐
          │          │  COMPLETED   │           │  FAILED   │
          │          │              │           │           │
          │          │ Normal end   │           │ Hook or   │
          │          │              │           │ dep failed│
          └─────────►│  ARCHIVED    │           └──────────┘
                     │              │
                     │ Kept for     │           ┌──────────┐
                     │ history      │           │ DELETED   │
                     └──────────────┘           │          │
                                                │ Gone     │
                                                └──────────┘
```

Every state transition is recorded in `transition_history`. This is both an audit trail and the source for the "history" dimension of the timeline — you can replay what was active at any past moment.

---

### Trigger Types

Triggers are the mechanism that causes state transitions. They're evaluated by the timeline engine during the tick loop.

#### Time Triggers

```
TimeTrigger {
  at: datetime              // fire at exact moment
  // OR
  cron: string              // "0 9 * * MON" — fire on schedule
  // OR
  relative: {               // fire relative to another event
    anchor: "entry_activated" | "entry_created" | "now"
    offset: duration        // "-2h" (before), "+30m" (after)
  }
}
```

Pre-computed: the engine calculates `next_fire_at` and only checks entries whose fire time has passed. O(1) per tick using a priority queue sorted by `next_fire_at`.

#### Event Triggers

```
EventTrigger {
  source: "email" | "saas" | "webhook" | "capsule" | "peer" | "system" | "user"
  match: {
    // Pattern matching against event payload
    from?: pattern           // "mom@*" or "did:key:z6Mk..."
    subject?: pattern        // "invoice*"
    type?: pattern           // "calendar.event.created"
    body?: pattern           // regex or semantic match
    metadata?: {key: pattern}
  }
}
```

Event triggers are push-based — when an event arrives on the event bus, the engine matches it against all registered event triggers. No polling needed. This is how "when email from mom arrives, activate this" works.

#### Condition Triggers

```
ConditionTrigger {
  predicate: {
    // Evaluated against current pod state
    type: "capsule_updated" | "entry_state" | "vault_query"
          | "external_state" | "expression"
    config: {
      // For capsule_updated:
      capsule_id: UUID, field?: string
      // For entry_state:
      entry_id: UUID, state: string
      // For expression:
      expr: string  // "active_entries.count(category='health') > 3"
    }
  }
  // Evaluated on relevant changes only (not every tick)
  // The engine knows which state changes could affect which conditions
  // and only re-evaluates when relevant state changes.
}
```

#### Dependency Triggers

```
DependencyTrigger {
  // Implicit from entry.depends_on
  // Entry transitions to PENDING when its activation trigger fires,
  // but stays in PENDING until all depends_on entries reach required_state.
  // The dependency graph is a DAG — cycles are rejected at creation time.
}
```

This is the **prerequisite** model. "Don't start X until Y is done." But unlike a task list, dependencies can require the upstream to be *active* (not just completed). "This entry is only relevant while that entry is active" — creating temporal coupling between entries.

#### Absence Triggers (important for proactivity)

```
AbsenceTrigger {
  // Fire when something DOESN'T happen
  expecting: {
    event?: EventMatch       // "expected email from X"
    entry_state?: {entry_id, state}  // "expected entry to complete"
  }
  deadline: datetime | duration  // "within 3 days"
  // If the expected thing hasn't happened by deadline → fire
}
```

This is uniquely powerful. "If I don't hear back from the doctor by Friday, remind me to follow up." No calendar or cron can express this — it's the *absence* of an event that triggers action.

---

### Hooks: What Happens on Transitions

Hooks are the **actions** that fire when entries change state. They're the bridge between the timeline engine (which manages state) and the rest of the system (which does things).

```
Hook {
  id: UUID
  phase: "pre" | "post"              // before or after the transition
  action: HookAction
  condition?: ConditionPredicate      // optional guard — only fire if true
  error_policy: "abort" | "continue" | "retry"  // what if hook fails
  timeout: duration                   // max time before considered failed
}

HookAction =
  | { type: "agent_task", prompt: string, tools?: [string], context?: any }
      // Ask the agent to do something. This is how the timeline drives proactivity.
      // Example: "Summarize the capsules linked to this entry and draft an email."

  | { type: "notify", channel: "push" | "email" | "ui" | "webhook", message: template }
      // Send a notification to the human owner or external system.

  | { type: "mutate_entry", target_entry_id: UUID, mutation: StateMutation }
      // Change another entry's state. Creates cascading state transitions.
      // Example: when entry A completes, force-activate entry B.

  | { type: "create_entry", template: EntryTemplate }
      // Spawn a new entry. Enables self-replicating patterns.
      // Example: recurring meeting creates next week's instance on completion.

  | { type: "vault_op", operation: "create" | "update" | "archive", capsule_config: any }
      // Modify the vault. Timeline entries can create/update capsules.

  | { type: "integration", adapter: string, action: string, config: any }
      // Call an external system. "Send email", "update Jira ticket", "post to Slack".

  | { type: "sync", target: "pool" | "peer" | "registry", payload: any }
      // Push state to the federation layer.

  | { type: "branch", action: "create" | "merge" | "discard", config: any }
      // Timeline branching operations.

  | { type: "pipeline", steps: [HookAction] }
      // Sequential chain of actions. Later steps can use output of earlier steps.
      // This is how complex multi-step proactive behaviors are composed.
```

The `agent_task` hook is the critical one. This is how the timeline **drives** the agent rather than the agent waiting for the human. When a timeline entry activates and its pre-hook is `agent_task`, the engine dispatches work to the agent with the entry's context. The agent reasons, uses tools, and returns a result — all triggered by time/events/conditions, not by a human typing.

---

### Central State: The Pod's "Process Table"

The central state is a **computed materialized view** of everything that's currently relevant. It's recomputed each tick (step 7). Nothing writes to it directly — it's derived from the state of all timeline entries plus pod metadata.

```
PodState {
  // Snapshot timestamp
  as_of: datetime
  tick_number: u64

  // What's happening right now
  active_entries: [{
    entry_id: UUID
    entry_type: string
    ref_uri: string
    activated_at: datetime
    salience: float
    category: string?
    resolved_summary: string?  // human-readable label
  }]

  // What's about to happen
  upcoming: [{
    entry_id: UUID
    fires_at: datetime
    trigger_type: string
    label: string
  }]

  // What's waiting
  pending: [{
    entry_id: UUID
    blocked_by: [UUID]        // dependency entry IDs
    blocked_reason: string    // human-readable
  }]

  // Attention signals — computed from patterns
  signals: [{
    severity: "info" | "attention" | "urgent" | "critical"
    message: string
    related_entries: [UUID]
    suggested_action?: string
  }]
  // Examples:
  //   { severity: "attention", message: "3 health entries expiring this week" }
  //   { severity: "urgent", message: "No response from Dr. Chen after 5 days" }
  //   { severity: "info", message: "Branch 'vacation-plan' has 4 unmerged entries" }

  // Resource usage
  resources: {
    active_entry_count: u32
    pending_trigger_count: u32
    vault_capsule_count: u32
    storage_used: bytes
    federation_peers: u32
    integration_mounts: u32
  }

  // Delta since last tick (for efficient UI updates)
  delta: {
    activated: [UUID]
    deactivated: [UUID]
    created: [UUID]
    signals_added: [signal]
    signals_resolved: [signal]
  }
}
```

This is what the agent consumes when it reasons. Instead of "I'm an AI with access to a vault, waiting for a question," the agent's context becomes: "Here's what's active on my owner's timeline right now, here's what needs attention, here's what's coming up." The agent can reason *temporally* — "this deadline is approaching and the prerequisite task isn't complete, I should alert my owner."

The delta model is important for efficiency: the UI doesn't re-fetch the entire state each tick — it receives only what changed.

---

### The Dependency Graph

Dependencies between entries form a **Directed Acyclic Graph (DAG)**. The engine evaluates this graph each tick to determine which pending entries can transition to active.

```
Example DAG:

  [Flight booked] ──────────┐
                             ▼
  [Hotel booked] ──────► [Travel prep]      [Packing list]
                             │                    │
                             ▼                    ▼
                        [Pre-trip agent         [Pack bags]
                         briefing]                 │
                             │                    │
                             ▼                    ▼
                        [Trip active] ◄───────────┘
                             │
                             ▼
                        [Trip debrief]
```

Rules:
- **Cycle detection**: the engine rejects any new dependency that would create a cycle.
- **Required state**: each dependency specifies whether the upstream must be `active` or `completed`. "Travel prep depends on flight booked being *completed*" vs "Packing list is only relevant while trip active is *active*."
- **Soft vs hard**: hard dependencies block activation. Soft dependencies generate warning signals but don't block.
- **Cross-timeline dependencies**: an entry on your timeline can depend on an entry on a shared pool timeline. "Don't start my part until the team milestone is reached." The engine resolves these through the sync layer.

---

### Reference Resolution

Timeline entries point to data — they don't hold it. The **reference resolver** translates URIs to actual content when an entry activates (and optionally caches it per `cache_policy`).

```
Resolver Pipeline:

  "capsule://abc-123"
    → Vault Manager
    → Decrypt with owner's vault key
    → Return plaintext content

  "saas://gcal/event/xyz"
    → Google Calendar integration adapter
    → OAuth token refresh if needed
    → Fetch event details via API
    → Return normalized event data

  "storage://s3/bucket/report.pdf"
    → Storage adapter
    → Fetch from S3 with credentials
    → Return file content or download link

  "pool://techcorp-team"
    → Trust enforcer checks visibility
    → Resolve pool's shared timeline and active entries
    → Return pool state summary

  "timeline://branch-42/entry-99"
    → Resolve entry on another timeline/branch
    → Apply visibility rules
    → Return entry state and resolved ref

  "webhook://external-service/callback"
    → Not resolved (outbound-only ref)
    → Used by hooks to push data out

  "compute://fn/summarize?input=capsule://abc-123"
    → Resolve input refs first
    → Execute compute function (could be agent-powered)
    → Return computed result
    → Cache per policy
```

The `compute://` ref type is interesting — it allows entries that point to **derived data**. "This entry's content is the summary of these three capsules, recomputed whenever any of them change." The resolved output is cached and invalidated when inputs change. This is lazy evaluation with caching — a familiar pattern from functional programming, applied to knowledge.

---

## The Event Bus

The event bus is the **nervous system** of PodOS. Everything that happens — internal or external — flows through it as events. The timeline engine consumes events during the tick loop (step 3: drain event queue).

```
Event {
  id: UUID
  timestamp: datetime
  source: EventSource
  type: string               // hierarchical: "email.received", "capsule.updated", etc.
  payload: any               // source-specific data
  metadata: {
    pod_id?: UUID            // if from a peer pod
    integration_id?: string  // if from a mounted integration
    entry_id?: UUID          // if generated by an entry hook
  }
}

EventSource =
  | "system"        // internal pod events (tick, startup, shutdown)
  | "user"          // human actions (login, manual trigger, UI interaction)
  | "agent"         // agent-generated events (task completed, insight found)
  | "integration"   // external system events (email, SaaS webhook, storage change)
  | "federation"    // peer pod events (message, sync, query)
  | "timeline"      // entry state transitions (activated, deactivated, hook fired)
```

### Event Flow

```
External world                    Pod boundary                    Timeline Engine
─────────────                    ─────────────                    ───────────────

Email arrives ──► Email Adapter ──► Event Bus ──► Queue ──► Tick drains queue
                                                               │
SaaS webhook ──► SaaS Adapter ──►    "         "    "         ├── Match against
                                                               │   event triggers
Peer message ──► Federation   ──►    "         "    "         ├── Transition
                                                               │   matching entries
User action  ──► UI/CLI/MCP  ──►    "         "    "         └── Fire hooks

Agent output ──► Agent Runtime ──►   "         "    "         (hooks may generate
                                                                more events →
                                                                next tick)
```

Events are **buffered** — they queue up between ticks. The engine drains the queue atomically during each tick. This prevents race conditions and ensures consistent state transitions. If the pod is under high load, events buffer; if the pod is sleeping, an event wakes it.

---

## Integration Adapters: Mounting the External World

The "mount point" analogy is literal. Integration adapters mount external systems into the pod's event space, making their data and events addressable through the standard `ref://` and event systems.

```
MountPoint {
  id: UUID
  adapter_type: "email" | "google_calendar" | "slack" | "github"
                | "s3" | "notion" | "custom_webhook"
  config: {
    credentials: encrypted_blob  // OAuth tokens, API keys, etc.
    scope: string                // what subset of the external system to mount
    sync_mode: "push" | "pull" | "bidirectional"
    poll_interval?: duration     // for pull-based adapters
  }
  mounted_at: string             // the URI prefix: "saas://gcal/*"
  state: "connected" | "disconnected" | "error"
  last_sync: datetime
}
```

### What Mounting Enables

**Mount Gmail:**
- Incoming emails become events on the event bus
- Timeline entries can reference specific emails: `saas://gmail/thread/abc123`
- Hook actions can send emails through the adapter
- "When email from `doctor@clinic.com` arrives, activate the 'medical results' entry"

**Mount Google Calendar:**
- Calendar events auto-generate timeline entries with appropriate time anchors
- But timeline entries have richer lifecycle — the gcal event is just the time anchor
- Pre/post hooks on the timeline entry do things gcal can't: "1 hour before meeting, have agent prepare briefing from relevant capsules"

**Mount GitHub:**
- PR merges, issue updates, CI results become events
- "When CI passes on feature branch, activate 'deploy review' entry"
- "When issue #123 is closed, deactivate the 'bug investigation' entry and archive linked capsules"

**Mount S3/Storage:**
- Files are addressable: `storage://s3/bucket/report.pdf`
- File changes generate events
- Timeline entries can point to files and activate when files are updated

The adapter pattern means PodOS doesn't need to understand every external system — it just needs adapters that translate external events and data into the standard event/ref protocols. New integrations are added as adapters, not as kernel changes.

---

## Branching: Parallel Timelines

A branch is a **fork of the timeline** that runs in parallel, ticking against real time, but isolated from the main timeline's state.

```
Main Timeline:     ─A─B─C─────D────E─────F───────►
                              │
Branch "what-if":             ├─X─Y────Z──────────►
                              │        │
Sub-branch:                   │        └─P─Q──────►
```

### Branch Semantics

A branch is **not** a copy. It's an **overlay**:
- The branch sees all main timeline entries as read-only shadows
- New entries on the branch only exist on the branch
- The branch has its own state machine — its entries activate/deactivate independently
- But time-based triggers use the same real clock

### Why Branches Matter

**Planning**: "What if I take this job?" Create a branch, add entries for the new commute, new schedule, new health insurance. The agent reasons about the branch's state — surfaces conflicts with existing commitments (visible as shadows from main), estimates impact. You review, then merge (accept the plan) or discard.

**Simulation**: "What happens if the project deadline moves to March 1?" Branch, modify the deadline entry, let the dependency graph cascade — watch what breaks. This is dry-run execution.

**Delegation**: "Handle the conference logistics" — create a branch for the agent to work in. The agent creates entries, resolves dependencies, drafts communications. The human reviews the branch and merges approved entries to main.

**Collaborative planning**: A shared pool timeline can have branches. Team members propose entries on branches; the pool owner merges approved ones. This is **pull requests for timelines**.

### Branch Rules

```
BranchPolicy {
  // Can hooks on this branch affect the real world?
  side_effects: "sandboxed" | "permitted"
  // "sandboxed": hooks are simulated, not actually fired
  //   → agent can reason but can't send emails
  // "permitted": hooks fire for real
  //   → agent delegation branch where actions are real

  // Auto-merge rules
  auto_merge: "never" | "on_approval" | "on_completion"

  // Conflict resolution
  on_conflict: "branch_wins" | "main_wins" | "manual"

  // Expiry
  ttl: duration?    // auto-discard if not merged within TTL
}
```

---

## Visibility: Trust Applied to Time

Every timeline entry has visibility rules that map to TrustMesh's existing trust model. This is what makes timelines shareable across pods and pools without leaking private information.

```
Visibility Levels (same as capsules):

  PRIVATE    → Only the owner's agent and the owner's UI can see this entry.
               Not shared with any pool or peer.

  INTERNAL   → Visible to pool members at "network" trust level.
               Shared on pool timelines. Peers in the pool see it.

  OPEN       → Visible to anyone who queries the pod.
               Appears on the pod's public timeline.
```

### Scoped Visibility

Beyond the three levels, entries can have **scoped visibility**:
- "Internal, but only to the 'Family Health' pool" — not all internal pools
- "Open, but only the entry metadata (type, time, category) — not the ref content"
- "Internal, but only the existence and time — not what it points to"

This creates a layered privacy model:

```
Layer 1: Entry existence       → "something is on the timeline at 3pm Tuesday"
Layer 2: Entry metadata        → "a health-related event at 3pm Tuesday"
Layer 3: Entry ref (pointer)   → "points to capsule://medical-results-123"
Layer 4: Resolved ref content  → "Blood test results showing..."

Each layer can have different visibility.
A pool member might see layers 1-3 but not 4.
The public might see layer 1 only.
```

### Shared Timelines

A pool can have a **shared timeline** — a timeline owned by the pool rather than an individual. Pool members can:
- See entries based on their trust level
- Propose entries (on a branch, merged by pool owner)
- Have their agents react to shared timeline state changes

```
Pool "Family Health Team":
  Shared Timeline:
    [Sarah's checkup — March 5] visibility: internal
      → all family members' agents see this
      → Dr. Johnson's agent has a pre-hook to prepare medical history
      → Sarah's parents' agents have a hook to check insurance status

    [Vaccination schedule — Q2] visibility: internal
      → each family member's agent checks their own records
      → agent creates draft entries on each person's timeline for appointments
```

Cross-pod visibility: when Pod A has a shared timeline entry visible at "internal" level, Pod B (a pool peer) sees it through the federation sync layer. Pod B's timeline engine creates a **shadow entry** — a read-only reference to Pod A's entry that appears in Pod B's state and can be depended upon by Pod B's own entries.

---

## The Agent in PodOS

In the current TrustMesh architecture, the agent is the center — it receives queries and responds. In PodOS, the agent is a **service** — one of several consumers of the timeline's central state.

### Agent Role Shift

```
Before PodOS:
  Human → Agent → Vault → Response
  (reactive, query-driven)

After PodOS:
  Timeline Engine → Central State → Agent → Actions
                                   ↗
                  Human ───────────
  (proactive, state-driven, with human as one input source among many)
```

The agent now has three modes of operation:

**1. Reactive (human-initiated)**
Human asks a question. Agent reads central state + vault + timeline context to answer. Same as today, but with much richer context (what's active, what's upcoming, what's blocked).

**2. Proactive (timeline-initiated)**
A hook fires `agent_task`. The engine dispatches work to the agent with context: "Entry X just activated, its pre-hook says to prepare a briefing." The agent reasons, uses tools, produces output, and the engine routes the output (notification to human, update to capsule, new entry on timeline, message to peer).

**3. Supervisory (continuous)**
The agent periodically reviews the central state's `signals` array and decides whether to act. "3 entries expiring this week — should I notify my owner?" This is a lightweight reasoning loop that runs on a longer interval (hourly, daily), examining the state holistically rather than responding to individual triggers.

### Agent Context Window

The central state serves as the agent's **working memory frame**. Instead of stuffing the entire vault into context, the agent sees:

```
System prompt: "You are {owner}'s agent on PodOS."
Timeline context: {
  active_entries: [...],    // what's live right now
  upcoming: [...],          // what's about to fire
  signals: [...],           // what needs attention
  recent_transitions: [...] // what just changed
}
Vault context: {
  // Only capsules referenced by active entries
  // or semantically relevant to the current task
}
Task: {
  // The specific hook, query, or supervisory check being executed
}
```

This is dramatically more focused than "here's all 500 capsules, answer a question." The timeline pre-filters relevance by time, state, and salience.

---

## Multi-Pod Coordination

When pods federate, their timelines need to coordinate. This introduces distributed systems concerns: clock skew, eventual consistency, conflict resolution.

### Sync Model

PodOS uses an **event-sourced sync model**. Pods don't sync their full state — they exchange **timeline events** (entry created, state changed, hook fired). Each pod applies these events locally, maintaining eventual consistency.

```
Pod A                          Pod B
──────                         ──────
Entry X created (shared)   ──► Shadow of X created on B's timeline
Entry X activated          ──► Shadow X marked active
Entry X hook fires         ──► B's engine sees shadow state change
                                B's entries depending on X can now activate
Entry X deactivated        ──► Shadow X deactivated
                                B's dependent entries deactivate (if linked)
```

### Clock Coordination

Pods don't need synchronized clocks (that's impractical). Instead:
- Each event carries its **pod-local timestamp**
- Sync messages include a **logical clock** (Lamport timestamp or vector clock)
- Causal ordering is preserved: if event A causally precedes event B, every pod applies A before B
- Time-based triggers use the local pod's clock, not the originating pod's clock

This means "activate at 3pm" fires at 3pm in each pod's local time (which might differ by timezone). For pool-coordinated deadlines, use UTC explicitly.

### Conflict Resolution

When two pods modify the same shared timeline entry concurrently:
- **Last-writer-wins** by default (using logical clocks to determine "last")
- **Pool owner wins** for pool-owned shared timelines
- **Split-brain protection**: if a pod detects divergent state, it generates a `conflict` signal in central state. The owner's agent or human resolves it.

---

## Worked Example: A Day in PodOS

Sarah Johnson's pod, morning:

```
6:00 AM — Heartbeat tick
  Central state: 2 entries activating

  Entry: "Morning health check"
    trigger: time, 6:00 AM daily
    ref: capsule://medication-schedule
    pre_hook: agent_task("Review medication schedule, check for any changes
              or interactions with newly added medications")
    → Agent reviews, finds no changes, marks hook complete
    → Entry goes active, will deactivate at 8:00 AM

  Entry: "Mom visiting this weekend"
    trigger: time, window start = Saturday 10 AM
    state: still dormant (it's Wednesday)
    pre_hook (2 days before activation): agent_task("Prepare for mom's visit:
              review dietary restrictions capsule, suggest meal plan,
              check if house prep tasks are complete")
    → Pre-hook fires Thursday morning (2 days before Saturday)
    → Agent will prepare the briefing then, not now

8:30 AM — Event arrives: email from dr.chen@clinic.com
  Event bus: email.received, from: dr.chen@clinic.com

  Entry: "Waiting for lab results"
    trigger: event, match: { from: "dr.chen@*", subject: "*results*" }
    state: dormant → pending
    depends_on: none
    → Transitions to activating
    pre_hook: agent_task("Read the lab results email, compare with previous
              results in capsule://health-records, summarize changes,
              flag anything concerning")
    → Agent processes, creates new capsule with summary
    post_hook (on deactivation): vault_op(archive capsule://lab-results-raw)
    → Notify owner: "Lab results received. Summary: all markers normal.
       Vitamin D slightly improved from last test."

9:00 AM — Tick evaluates dependencies
  Entry: "Schedule follow-up with Dr. Chen"
    depends_on: ["Waiting for lab results" must be COMPLETED]
    state: pending (was waiting for dep)
    → Lab results entry completed → dep satisfied
    → Transitions to activating
    pre_hook: agent_task("Based on the lab results summary, draft a follow-up
              email to Dr. Chen. If results are normal, suggest 6-month follow-up.
              If abnormal, suggest urgent appointment.")
    hook fires integration://gmail, action: draft_email(...)
    → Agent drafts email, sends via gmail adapter
    → Owner gets notification: "Drafted follow-up email to Dr. Chen. Review?"

3:00 PM — Shared pool timeline event
  Pool "Family Health Team" shared timeline:
    Entry: "Family flu shot coordination — October"
    source: Dr. Johnson's pod (pool owner)
    → Shadow entry created on Sarah's timeline
    → Sarah's agent sees it in central state
    → Agent proactively: "Your dad scheduled flu shots for the family in October.
       Based on your calendar, October 15th works. Shall I respond?"
```

This is one morning. No human initiated any of this. The timeline engine drove the agent through time triggers, event triggers, and dependencies. The human saw notifications and approved actions. **The agent was proactive because the timeline made it so** — not because of polling, not because of a cron job, but because the lifecycle of timeline entries naturally generates agent work.

---

## What This Means for TrustMesh

PodOS isn't a rewrite — it's recognizing that TrustMesh already has most of the pieces, and the timeline engine is the missing core that connects them.

```
Existing TrustMesh       →    PodOS Role
──────────────────              ─────────
Capsules (vault)          →    Ref targets (what entries point to)
Trust levels              →    Entry visibility rules
Connections/Networks      →    Sync topology for shared timelines
Federation (pod-to-pod)   →    Distributed timeline sync
Agent (Sonnet 4.5)          →    Service consumer of central state
Citadel (security)        →    Scans on ref resolution + hook output
UCAN tokens               →    Emergency override triggers
Ghost users               →    Shadow entries from peer timelines
MCP server                →    Layer 4 interface to timeline
CLI                       →    Layer 4 interface to timeline
```

What's **new**:
- Timeline engine (the tick loop, state machine, trigger system)
- Entry model (the lifecycle primitive)
- Dependency graph (DAG evaluation)
- Event bus (unified internal/external event routing)
- Integration adapters (mount external systems)
- Branch system (parallel timeline exploration)
- Central state (computed process table)
- Adaptive scheduling (event-woken with heartbeat floor)

### Implementation Path

This is a foundational change, but it doesn't have to be built all at once:

**Phase 1: Entry model + tick loop**
Add timeline entries alongside capsules. Simple time triggers only. No dependencies, no branching. This alone enables "remind me" and "activate at time X" patterns.

**Phase 2: Event bus + integration adapters**
Add the event system. Mount email as the first adapter. Event triggers now work. "When email from X arrives, do Y."

**Phase 3: Dependencies + central state**
Add the DAG. Compute central state. Agent starts consuming timeline context instead of raw vault queries. Proactivity emerges.

**Phase 4: Branching + shared timelines**
Add branches for planning. Add shared timelines for pools. Full PodOS.

---

## Learning From Temporal: What to Steal, What to Reject

Temporal.io is the closest prior art to the timeline engine. It's battle-tested, well-funded ($350M total, [$1.72B→$2.5B valuation](https://finance.yahoo.com/news/temporal-technologies-secures-146m-1-130800695.html)), and massively adopted (183,000 weekly active OSS developers, 2,500+ cloud customers, [4.4x revenue growth in 18 months](https://www.swyx.io/temporal-centicorn)). Netflix, Snap, Datadog, HashiCorp run it in production. It's the "React for the backend" — swyx makes a [$100B bull case](https://www.swyx.io/temporal-centicorn) for it becoming the reliability layer for all long-running computation.

We should study it seriously. But we should also understand exactly where it stops and the timeline begins.

### What Temporal Gets Right (Steal This)

**1. Durable execution**
Temporal's core insight: workflow state is persisted as an event history. If a process crashes mid-execution, it replays the event history and resumes from the exact point of failure. Nothing is lost. This is "fault-oblivious stateful" computing — your code doesn't know it crashed.

→ **Steal**: The timeline engine should persist entry state transitions as an event log. If the pod crashes mid-tick, it replays the log on restart and resumes. Entry state is never lost.

**2. Activities as retryable units**
Temporal separates workflows (the coordination logic) from activities (the actual work). Activities are automatically retried with configurable policies. If an API call fails, Temporal retries it without the workflow knowing.

→ **Steal**: Hooks should have retry policies. If an `agent_task` hook fails (LLM rate limit, timeout), the engine retries with backoff. If an `integration` hook fails (email API down), it queues for retry. The entry stays in `activating` until its hooks complete or exhaust retries.

**3. Signals for external events**
Temporal workflows can receive "signals" — external events that inject data into a running workflow. A workflow can pause and wait for a signal indefinitely.

→ **Steal**: This is exactly our event trigger model. An entry in `dormant` state waiting for an event signal is a Temporal workflow waiting for a signal. The concept is proven.

**4. Timers and schedules**
Temporal supports durable timers — "wake me up in 3 days" — that survive process restarts. And scheduled workflows that fire on cron expressions.

→ **Steal**: Time triggers should be durable. Persisted to disk, survive restarts, pre-computed for efficient evaluation.

**5. Observability**
Every step, every decision, every retry is logged in the event history. You can inspect exactly what happened, when, and why.

→ **Steal**: The `transition_history` on each entry is our version of this. Full audit trail of every state change, every hook fire, every trigger evaluation.

### Where Temporal Falls Short (The Gap)

**1. Pre-defined vs emergent**
Temporal workflows are **written in code, deployed, then executed**. You define `async def my_workflow()` → deploy it → start instances of it. The workflow topology (what happens in what order) is fixed at code time.

Timelines are **emergent**. Entries come and go at runtime. A human adds an idea. An agent creates a task. An email triggers a new entry. A pool pushes a shared entry. The "workflow" isn't pre-defined — it's the living state of all active entries and their dependencies. It's more like a running OS process table than a deployed workflow definition.

**2. No trust or visibility model**
Temporal workflows are internal to an organization. There's no concept of "this step is private, this step is visible to partners, this step is public." Everything in a Temporal namespace is equally accessible to anyone with credentials.

Timelines have trust baked in at the entry level. Private > Internal > Open, with scoped visibility and per-layer disclosure (existence vs metadata vs ref vs content). This is fundamental, not bolted on.

**3. No temporal anchoring**
Ironic given the name — Temporal workflows aren't anchored to real-world time in a meaningful way. They can have timers ("wait 3 days") but they don't have a concept of "this workflow is relevant during the window of March 5-10" or "this workflow deactivates when a real-world event ends."

Timeline entries ARE temporal — they have anchors, windows, horizons. Time isn't just "when to fire a timer" — it's a fundamental property of the entry's relevance.

**4. No hierarchy or resolution**
Temporal has namespaces, but no priority hierarchy. If two workflows produce conflicting results, there's no built-in resolution model. You'd have to build that yourself.

The timeline's Private > Internal > Open resolution hierarchy is structural. Conflicts resolve by specificity. Always. Without custom code.

**5. No federation**
Temporal Cloud is centralized. Your workflows run on Temporal's servers (or your self-hosted cluster). There's no concept of "my Temporal instance federates with your Temporal instance through trust boundaries."

Timelines federate. Pods exchange entry state through pools. Shadow entries appear on peer timelines. This is native to the model, not an add-on.

**6. No human-in-the-loop as first class**
Temporal can model human approvals (workflow waits for signal, human sends signal), but the human isn't a first-class participant. The human experience is "you got an alert, click approve in the admin UI."

In the timeline, humans and agents see the same entries through different lenses. The human's calendar view, the agent's state view — both are projections of the same timeline. The human isn't approving a workflow step; they're participating in a shared temporal reality.

### The Synthesis

Think of it this way:

```
Temporal = durable workflow execution engine for backend services
Timeline = durable lifecycle engine for entities (humans + agents + orgs)
```

Temporal asks: "How do I reliably execute this sequence of operations?"
Timeline asks: "What's happening in this entity's world right now, what's about to happen, and what should the agent do about it?"

Temporal is infrastructure. Timeline is experience. Temporal runs in a data center. Timeline runs on your device. Temporal coordinates microservices. Timeline coordinates a life.

They could even coexist: the timeline engine's hook execution layer could use Temporal-style durable execution for complex multi-step hooks. Temporal becomes an implementation detail of the timeline's hook dispatch, not a replacement for the timeline itself.

---

## The Three-Stream Architecture: Public → Pool → Pod

The timeline isn't one thing. It's three concurrent streams at different trust levels, unified into a single resolution model. This is where PodOS meets TrustMesh's existing Pod → Pool → Public architecture.

### The Three Streams

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  STREAM 3: PUBLIC TIMELINE (The Registry)                          │
│  ═══════════════════════════════════════                            │
│                                                                     │
│  The public agent registry IS a timeline stream. Any pod can        │
│  subscribe. Entries are OPEN visibility. This is the "internet"    │
│  of timelines — global, discoverable, low-trust.                   │
│                                                                     │
│  Entry types: agent registrations, service announcements,           │
│  public events, capability broadcasts, discovery signals            │
│                                                                     │
│  Resolution priority: LOWEST (overridden by pool and pod)          │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  STREAM 2: POOL TIMELINES (Shared Trust Groups)                    │
│  ═══════════════════════════════════════════════                    │
│                                                                     │
│  Each pool has a shared timeline. Members subscribe via pool        │
│  membership. Entries are INTERNAL visibility. This is the "LAN"    │
│  of timelines — trusted group, coordinated, medium-trust.          │
│                                                                     │
│  Entry types: group events, shared milestones, coordinated tasks,  │
│  member announcements, collaborative planning branches              │
│                                                                     │
│  A pod can subscribe to MULTIPLE pool timelines (family pool,      │
│  work pool, health pool). Each is a separate stream.               │
│                                                                     │
│  Resolution priority: MIDDLE (overrides public, overridden by pod) │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  STREAM 1: POD TIMELINE (Your Main Timeline)                       │
│  ═══════════════════════════════════════════                        │
│                                                                     │
│  Your pod's main timeline. Only you and your agent see PRIVATE     │
│  entries. INTERNAL entries are shared with your pools. OPEN         │
│  entries are visible to anyone.                                     │
│                                                                     │
│  Entry types: everything — personal events, ideas, tasks, health,  │
│  reminders, hooks, data refs, branches, private plans              │
│                                                                     │
│  Resolution priority: HIGHEST (always wins)                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### How Streams Merge: The Resolution Model

Each tick, the timeline engine merges all three streams into a single **resolved view**. This is the central state — what the agent actually sees and acts on.

```
TICK Phase — Stream Resolution:

  1. GATHER
     Collect all active/pending entries from:
     ├── Pod timeline (local)
     ├── Pool timelines × N (from sync cache)
     └── Public stream (from registry subscription)

  2. INDEX BY TIME
     Place all entries on a unified time axis.
     Entries may overlap in time windows.

  3. RESOLVE CONFLICTS (Private > Internal > Public)
     For overlapping entries in the same time window + category:
     ├── Pod entry exists? → Pod wins. Shadow pool/public entries.
     ├── Pool entry exists? → Pool wins over public.
     └── Only public? → Public stands.

     Conflict detection is by CATEGORY + TIME overlap, not exact match.
     "Work meeting at 3pm" (public) vs "Focus time 2-5pm" (pod/private)
     → Private focus time wins, public meeting is shadowed.

  4. APPLY VISIBILITY FILTERS
     For each resolved entry, determine what's visible to whom:
     ├── Agent sees everything (all three streams, resolved)
     ├── Human UI sees pod entries + subscribed pool entries
     ├── Pool peers see only INTERNAL+ entries from this pod
     └── Public queries see only OPEN entries

  5. COMPUTE CENTRAL STATE
     The resolved, visibility-filtered, conflict-resolved set of
     active entries becomes the central state for this tick.
```

### The Resolution Hierarchy in Practice

```
Scenario: Dr. Johnson's Thursday afternoon

PUBLIC STREAM (registry):
  14:00-15:00  "City Health Department: Free flu vaccinations at Community Center"
               visibility: open, category: health
               → Any subscribed pod sees this

POOL STREAM (Family Health Team):
  14:00-16:00  "Family check-in: Review Sarah's latest lab results"
               visibility: internal, category: health
               → Pool members' agents see this
               → OVERRIDES the public flu vaccination entry for this time

POD TIMELINE (Dr. Johnson's private):
  14:30-15:30  "Prepare for difficult conversation with Sarah about results"
               visibility: private, category: health
               pre_hook: agent_task("Pull Sarah's full health history,
                         draft talking points, review emotional context")
               → OVERRIDES both pool and public entries
               → Only Dr. Johnson's agent sees this
               → Agent prepares briefing proactively

RESOLVED CENTRAL STATE for Dr. Johnson at 14:30:
  ACTIVE (visible to agent):
    1. [PRIVATE] "Prepare for difficult conversation" — salience: 0.95
    2. [INTERNAL] "Family check-in: Review Sarah's results" — salience: 0.7 (shadowed)
    3. [OPEN] "Free flu vaccinations" — salience: 0.2 (shadowed)

  Agent sees all three but knows #1 takes priority.
  The human's calendar view shows only "Family health time 2-4pm"
  (the private detail is hidden even from the calendar display,
  shown only when the human explicitly opens the entry).
```

### The Public Registry as a Timeline Stream

Today the TrustMesh registry is a static directory: "here are registered agents with their capabilities." As a timeline stream, it becomes alive:

```
Public Timeline Stream (hosted by registry):

  PERSISTENT ENTRIES (always active):
    "TechCorp: AI consulting available"
      ref: agent-card://did:key:z6MkTechCorp
      type: service_announcement
      visibility: open
      → Any subscribing pod's agent can see this
      → Hook: when someone queries for "AI consulting", surface this

    "City Hospital: Emergency services 24/7"
      ref: agent-card://did:key:z6MkCityHospital
      type: service_announcement
      visibility: open

  TEMPORAL ENTRIES (time-bound):
    "TechCorp: Hiring AI Engineers — Q1 2026"
      ref: url://techcorp.com/careers/ai-engineer
      anchor: window { start: Jan 1, end: Mar 31 }
      visibility: open
      → Activates Jan 1, deactivates Mar 31
      → Subscribing pods' agents check owner's career capsules
      → "TechCorp is hiring AI engineers. Based on your skills, you're a match."

    "City Health Dept: Flu Season Advisory — Oct-Feb"
      ref: capsule://public-health-advisory-2026
      anchor: window { start: Oct 1, end: Feb 28 }
      visibility: open
      pre_hook: broadcast to subscribed health-category pods

  EVENT-DRIVEN ENTRIES:
    "Emergency: Water Main Break — Downtown District"
      ref: url://city.gov/alerts/water-main-2026-02
      trigger: event (published by government pod)
      visibility: open
      ttl: until resolved
      → All subscribing pods in affected area get this
      → Agents proactively notify owners, reschedule affected plans
```

The registry isn't just a phone book anymore. It's a **living public stream** that pods subscribe to. Events flow from registry to pods. Pods' timeline engines process them like any other event source. The agent reasons about public entries just like private ones — but at the lowest resolution priority.

### Pod Subscribes to Streams

```
Dr. Johnson's Pod Timeline Engine:

  SUBSCRIPTIONS:
    ├── Public stream: registry.trustmesh.net/timeline
    │   Filter: categories [health, local, emergency]
    │   Resolution: LOWEST priority
    │
    ├── Pool: "Family Health Team" shared timeline
    │   Filter: all entries (trusted pool)
    │   Resolution: MIDDLE priority
    │
    ├── Pool: "Medical Staff Network" shared timeline
    │   Filter: categories [health, admin, schedule]
    │   Resolution: MIDDLE priority
    │
    └── Pod: main timeline (local)
        Filter: none (everything)
        Resolution: HIGHEST priority

  Each tick:
    1. Drain events from ALL subscribed streams
    2. Create shadow entries for external entries
    3. Resolve conflicts across all streams (private > internal > open)
    4. Compute unified central state
    5. Agent sees one coherent view of "what matters now"
```

### How State Flows Between Layers

State doesn't just flow downward (public → pod). It flows **upward** too. A pod can publish entries to pool and public streams:

```
UPWARD FLOW (pod → pool → public):

  Pod creates entry:
    "New research paper published on cardiac genetics"
    visibility: INTERNAL
    → Automatically pushed to "Medical Staff Network" pool timeline
    → Pool members' agents see it on next tick

  Pod creates entry:
    "Dr. Johnson: Available for cardiac consultations"
    visibility: OPEN
    → Pushed to pool timelines (internal view with full details)
    → AND pushed to public registry stream (open view with limited metadata)
    → Registry subscribers see: "Cardiac specialist available"
    → Pool members see: "Dr. Johnson available, phone: ..., schedule: ..."

DOWNWARD FLOW (public → pool → pod):

  Registry publishes:
    "FDA: New drug interaction warning for Medication X + Y"
    visibility: OPEN
    → All subscribing pods receive this
    → Pod's engine checks: does owner have capsules mentioning X or Y?
    → If yes: auto-create a PRIVATE entry on pod timeline:
        "ATTENTION: Drug interaction warning affects your medications"
        salience: 0.95, pre_hook: agent_task("Review and alert owner")
    → The public entry spawned a private entry with higher priority

LATERAL FLOW (pool ↔ pool via pod):

  Pod is member of Pool A ("Family Health") and Pool B ("Insurance Group")
  Pool A creates entry: "Sarah needs specialist referral"
  Pod's agent sees this → checks Pool B → finds relevant provider
  Pod creates entry on Pool B timeline: "Referral needed for member"
  → Two pools coordinated through the pod, without direct pool-to-pool connection
  → The pod is the bridge, the timeline is the coordination mechanism
```

### Entry Lifecycle Across Streams

An entry's lifecycle can span multiple streams:

```
LIFECYCLE EXAMPLE: "Sarah's Annual Checkup"

1. PUBLIC STREAM (origin):
   "City Hospital: Annual checkup reminders — book by March"
   trigger: time, January 1
   visibility: open
   → Dr. Johnson's pod receives this via public subscription

2. POD TIMELINE (internalized):
   Pod agent creates private entry:
   "Schedule Sarah's annual checkup"
   trigger: dependency (waits for insurance verification)
   visibility: private
   depends_on: ["Insurance coverage verified" entry]
   pre_hook: agent_task("Check Sarah's last checkup date,
             review any health changes since then,
             find available appointments")

3. POOL TIMELINE (coordinated):
   Agent publishes to "Family Health Team" pool:
   "Sarah's checkup: March 5, 2pm — City Hospital"
   visibility: internal
   pre_hook: notify all pool members
   → Mom's agent: "Sarah has a checkup March 5. Offer to drive?"
   → Dad's agent: "Sarah has a checkup March 5. Prepare insurance card."

4. POD TIMELINE (execution):
   Agent creates private entries for preparation:
   "Compile health questions for Dr. Chen" — depends_on: [checkup entry active]
   "Print insurance card" — trigger: time, March 4
   "Post-checkup: update health records" — trigger: event, checkup completed

5. PUBLIC STREAM (outcome, optional):
   If Dr. Johnson enables it, a sanitized entry appears:
   "Dr. Johnson's pod: Health checkup completed, records updated"
   visibility: open (metadata only — no health details)
   → Other healthcare providers' agents note the update
```

One real-world event ("annual checkup") touches all three streams across its lifecycle. The timeline engine coordinates this seamlessly — the human sees "checkup on March 5" in their calendar view, while underneath, entries are activating, hooks are firing, agents are coordinating, and state is flowing between pod, pool, and public streams.

### Events, Hooks, and Resolution: The Full Picture

```
┌──────────────────────────────────────────────────────────────────┐
│                    THE FULL TICK-TOCK CYCLE                       │
│                                                                  │
│  EVENTS (inputs to the system):                                  │
│  ├── Time events: wall clock advances                            │
│  ├── External events: email, webhook, SaaS notification          │
│  ├── Federation events: peer pod message, pool sync              │
│  ├── Public stream events: registry entry created/updated        │
│  ├── User events: human action in UI/CLI                         │
│  ├── Agent events: agent task completed, insight generated        │
│  └── System events: pod startup, health check, resource alert    │
│                                                                  │
│                          ▼                                       │
│                                                                  │
│  TICK (evaluate — frozen state):                                 │
│  ├── Drain event queue                                           │
│  ├── Match events to entry triggers across ALL streams           │
│  ├── Evaluate dependency DAG                                     │
│  ├── Resolve conflicts: PRIVATE > INTERNAL > OPEN                │
│  ├── Build transition plan                                       │
│  │                                                               │
│  │   Resolution rules:                                           │
│  │   ├── Same category + overlapping time = conflict             │
│  │   ├── Higher-priority stream wins (pod > pool > public)       │
│  │   ├── Within same stream: explicit depends_on ordering        │
│  │   ├── Shadowed entries still exist, just lower salience       │
│  │   └── Shadowed ≠ deleted. If private entry deactivates,       │
│  │       the pool/public entry resurfaces automatically.          │
│  │                                                               │
│  ├── Validate: no cycles, no impossible states, resource limits  │
│  └── Produce: TransitionPlan [(entry, old_state, new_state,      │
│                                hooks_to_fire, resolution_note)]  │
│                                                                  │
│                          ▼                                       │
│                                                                  │
│  TOCK (commit — apply changes):                                  │
│  ├── Apply state transitions atomically                          │
│  ├── Fire pre-hooks:                                             │
│  │   ├── agent_task → dispatch to agent runtime (async)          │
│  │   ├── notify → push to notification service                   │
│  │   ├── vault_op → modify capsules in vault                     │
│  │   ├── integration → call external system via adapter          │
│  │   ├── mutate_entry → enqueue internal event (next tick)       │
│  │   └── sync → push to federation layer                         │
│  ├── Update central state snapshot                               │
│  ├── Fire post-hooks (same types as above)                       │
│  ├── Persist transition log (for durability + replay)            │
│  ├── Emit deltas to subscribers (UI, agent, sync)                │
│  ├── Push INTERNAL entries to pool streams                       │
│  ├── Push OPEN entries to public stream (registry)               │
│  └── Compute next wake time, sleep                               │
│                                                                  │
│                          ▼                                       │
│                                                                  │
│  STATE (outputs of the system):                                  │
│  ├── Central state: unified resolved view for agent              │
│  ├── UI state: filtered view for human (calendar, dashboard)     │
│  ├── Pool state: shared entries visible to pool peers            │
│  ├── Public state: open entries visible to registry              │
│  ├── Transition log: persistent history for replay + audit       │
│  └── Metrics: tick duration, entry counts, hook latencies        │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### How the Zig Kernel Fits with the Host OS

The Zig timeline kernel doesn't replace the host operating system. It's a **userspace daemon** that leverages the host OS for I/O, networking, and process management, but owns the timeline state machine, resolution logic, and tick-tock cycle.

```
┌────────────────────────────────────────────────────────────────┐
│  HOST OS (macOS, Linux, Android, etc.)                         │
│                                                                │
│  Provides: filesystem, network sockets, process scheduling,    │
│  memory management, device I/O, system clock                   │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  PodOS Zig Kernel (userspace daemon)                     │  │
│  │                                                          │  │
│  │  OWNS:                                                   │  │
│  │  ├── Timeline engine (tick-tock loop)                    │  │
│  │  ├── Entry state machines (lifecycle transitions)         │  │
│  │  ├── Dependency DAG (evaluation + cycle detection)        │  │
│  │  ├── Event bus (queue + trigger matching)                │  │
│  │  ├── Stream resolution (private > internal > open)        │  │
│  │  ├── Central state computation                           │  │
│  │  ├── Transition log (durability + replay)                │  │
│  │  └── Ref URI parser + router (dispatches to host layer)  │  │
│  │                                                          │  │
│  │  DELEGATES TO HOST OS:                                   │  │
│  │  ├── File I/O (via syscalls) → SQLite, vault files       │  │
│  │  ├── Network I/O (via sockets) → federation, sync        │  │
│  │  ├── Process management → agent runtime, adapters         │  │
│  │  └── System clock → wall time for tick scheduling         │  │
│  │                                                          │  │
│  │  EXPOSES TO HOST LAYER (Python/TS):                      │  │
│  │  ├── C ABI or Unix domain socket                         │  │
│  │  ├── create_entry(entry) → entry_id                      │  │
│  │  ├── update_entry(id, mutation) → ok/err                 │  │
│  │  ├── subscribe_stream(url, filter) → subscription_id     │  │
│  │  ├── push_event(event) → ok/err                          │  │
│  │  ├── get_central_state() → PodState                      │  │
│  │  ├── register_hook_handler(type, callback) → handler_id  │  │
│  │  └── get_transition_log(since) → [transitions]           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Host Layer (Python / TypeScript)                        │  │
│  │                                                          │  │
│  │  Agent Runtime:                                          │  │
│  │  ├── Receives agent_task hooks from kernel               │  │
│  │  ├── Calls LLM (Sonnet 4.5) with central state context    │  │
│  │  ├── Executes tools (search, save, query)                │  │
│  │  └── Returns results as events to kernel                 │  │
│  │                                                          │  │
│  │  Integration Adapters:                                   │  │
│  │  ├── Email adapter (IMAP/SMTP → events)                  │  │
│  │  ├── Calendar adapter (CalDAV/Google → entries)           │  │
│  │  ├── SaaS adapters (webhooks → events)                   │  │
│  │  └── Storage adapters (S3/local → refs)                  │  │
│  │                                                          │  │
│  │  Vault Manager:                                          │  │
│  │  ├── AES-256-GCM encrypt/decrypt                         │  │
│  │  ├── Capsule CRUD                                        │  │
│  │  └── Ref resolution for capsule:// URIs                  │  │
│  │                                                          │  │
│  │  Federation:                                             │  │
│  │  ├── Peer-to-peer sync (push/pull timeline events)       │  │
│  │  ├── Pool sync (shared timeline coordination)            │  │
│  │  └── Registry sync (public stream subscription)          │  │
│  │                                                          │  │
│  │  Human Interface:                                        │  │
│  │  ├── Web UI (Next.js — calendar view, dashboard)         │  │
│  │  ├── CLI (terminal commands)                             │  │
│  │  └── MCP (programmatic access from Claude Code, etc.)    │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

The kernel communicates with the host layer through a thin API surface. The host layer handles everything that requires external dependencies (LLMs, encryption libraries, HTTP clients, UI frameworks). The kernel handles everything that must be fast, deterministic, and reliable (state machines, DAG evaluation, conflict resolution, event matching).

This separation means:
- The kernel can be tested exhaustively without LLMs, networks, or external services
- The kernel binary is small (~1-5MB), portable, and embeddable
- Different host layers can wrap the same kernel (Python for desktop, Swift for iOS, Kotlin for Android)
- The kernel's tick-tock never blocks on slow external operations (hooks are async, results come back as events)

---

## Edge Cases & Solutions

See the full implementation plan at [`poc-timeline-kernel.md`](./poc-timeline-kernel.md) for detailed edge case solutions with implementation specifics. Summary:

| # | Edge Case | Solution | Priority |
|---|-----------|----------|----------|
| EC-1 | Pod goes offline | Event-sourced catch-up on reconnect, missed-entry summary | High |
| EC-2 | Dangling ref (capsule deleted) | Graceful `ref_unavailable` → entry fails → agent handles | Medium |
| EC-3 | Privacy leak via pool sync | Visibility upgrade confirmation + category-scoped pool filters + Citadel scan | Critical |
| EC-4 | Clock skew between pods | UTC anchors for shared entries + Lamport timestamps for causal ordering | High |
| EC-5 | Cascade storm (infinite hooks) | Tick-tock isolation + cascade depth limit + per-tick hook cap | Critical |
| EC-6 | Pool member removal | Shadow entries archived + dependency signals + mirrors ghost cleanup | Medium |
| EC-7 | Registry goes down | Local+pool unaffected, OPEN entries buffer, reconnect+catch-up | Low |
| EC-8 | Large backlog after offline | Batch catch-up mode, expired entry pruning, single agent summary | Medium |
| EC-9 | Split-brain pool updates | Last-writer-wins with logical clocks, pool owner tiebreaker | Medium |
| EC-10 | Agent task hook timeout | Per-hook timeout + retry with backoff + entry stays in activating | High |

---

## Open Questions

These need further design work:

1. **State persistence**: Is the central state persisted (survives pod restart) or computed from entries on startup? Probably computed, with entries as the source of truth. But cold-start recomputation of a large timeline could be slow — may need checkpointing.

2. **Entry garbage collection**: Completed/archived entries accumulate. When do they get pruned? Keep N days of history? Configurable per entry type?

3. **Hook execution model**: Are hooks synchronous (engine waits for completion) or async (fire and continue)? Probably async with timeouts — the engine can't block on a slow LLM call. But then how do we handle pre-hooks that gate activation?

4. **Agent resource management**: If the timeline fires 10 `agent_task` hooks simultaneously, that's 10 concurrent LLM calls. Need queuing, prioritization, and budget limits. Salience could drive priority.

5. **Schema evolution**: As the entry model evolves, how do we migrate existing entries? Versioned entry schemas with migration functions?

6. **Trust inheritance on branches**: If a main timeline entry is "internal" and gets shadowed on a branch, is the branch entry also "internal"? What if the branch has different visibility rules?

7. **Real-time vs batch**: Some pods (personal, always-on laptop) want real-time ticking. Others (org pod on a server) might want batch processing. The engine should support both modes.

8. **Entry composition**: Can an entry's ref point to a query (like a saved search) rather than a static resource? "This entry activates when any capsule matching 'health + abnormal' appears." This blurs the line between entries and standing queries.

9. **Edge storage format**: The encrypted flat file concept (Parquet-inspired, pool-key encrypted, on R2/S3) needs format specification. Column-oriented for metadata queries without full decryption? Or simpler encrypted blobs? Trade-off: query flexibility vs implementation complexity.

10. **Pool shared key lifecycle**: Key exchange on pool formation, rotation on member change — but what about key escrow? If all members lose their key, edge data is gone. Acceptable for trust-first design, or need a recovery path?

---

## Agent Operating Modes

Operating modes aren't a special API. They're an emergent property of an agent's public timeline entries. When Riverside Hospital publishes OPEN entries like "Outpatient Hours: Mon-Fri 8am-5pm" and "Flu Vaccination Walk-in: Feb 15 – Mar 15", those entries' lifecycle states define what the hospital is currently doing.

The registry runs its own PodOS kernel whose timeline IS the public stream. When you query `GET /api/agents?when=now&tags=health`, the registry reads its kernel's central state — the already-computed set of currently active entries — groups them by publisher, and returns agents with their live activities.

This means temporal discovery is not a search feature bolted onto the registry. It IS the registry's kernel doing its normal work.

Tags are free-form strings on entries (e.g., `["health", "vaccination", "walk-in"]`). Pods subscribe to the public stream with tag filters so they only receive relevant entries. No global taxonomy needed — tags are emergent, like hashtags.

See [`poc-timeline-kernel.md`](./poc-timeline-kernel.md) §11 for the full API design and implementation plan.

---

## Encrypted Edge Storage

When a pod goes offline, its capsules become inaccessible to pool members. For personal pods this is fine — your data sleeps with you. For organization pods or time-sensitive pools, it's a problem.

The solution: Parquet-inspired encrypted flat files on edge storage (R2, S3, any object store) that pool members can read when the originating pod is offline. Pool shared key encrypts. Pod ed25519 signs. Only INTERNAL-visibility capsules export — PRIVATE stays on-pod.

This is a **future phase** (not in the initial PoC) but the timeline accommodates it naturally: export operations are timeline entries with hooks, freshness tracking is a computed entry with rising salience as staleness grows, and reconciliation on reconnect is a standard catch-up event.

See [`poc-timeline-kernel.md`](./poc-timeline-kernel.md) §12 and Phase 7 for the full design.

---

## Philosophical Note

The reason this feels like an OS is because it *is* one. We've been building AI agent systems as applications — a chatbot with tools, sitting on top of a regular computer's OS. But the computer's OS was designed for files and processes, not for knowledge with trust boundaries and temporal lifecycle.

PodOS says: the pod IS the computer. The timeline IS the process model. The vault IS the file system. Trust IS the permission model. Federation IS the network. The agent IS user space.

Everything else — the human's calendar view, the CLI, the web UI, the MCP interface — those are just shells. Different ways to interact with the same underlying system. Just like bash and zsh and a GUI file manager are all shells over the same Unix kernel.

The calendar is a shell. The timeline is the kernel.
