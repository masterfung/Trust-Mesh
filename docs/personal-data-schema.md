# Personal Data Schema & Temporal Knowledge

## The Problem

Free-form capsules don't scale. At 3000+ capsules:
- **Discovery**: "Do I already have a capsule about my diet?" — no way to know
- **Duplication**: 5 capsules all mention grandma's medication with slightly different dosages
- **Contradiction**: "I'm vegetarian" (March) vs "I'm pescatarian" (June) — which is current?
- **Context bloat**: Agent gets 20 capsules about health when only 3 are relevant
- **No schema**: "allergies" could be in a preference, memory, or procedure capsule

## Solution: Structured Fields + Temporal Versioning

Instead of only free-form capsules, introduce **structured personal data fields** that are:
- Schema-defined (known field types with validation)
- Temporally versioned (every change is tracked, old values kept as history)
- Automatically deduplicated (one canonical value per field)
- Category-organized (self, health, work, hobbies, etc.)

**Capsules remain** for rich, narrative knowledge (procedures, memories, skills). But structured fields handle the **factual data** that changes over time.

## Data Categories

```
Personal Data
├── SELF (identity & preferences)
│   ├── display_name: "Sasha Rivera"
│   ├── pronouns: "she/her"
│   ├── birthday: "1992-03-15"
│   ├── diet: "pescatarian"           ← was "vegetarian" before June
│   ├── languages: ["English", "Spanish"]
│   ├── personality_notes: "Introvert, prefers text over calls"
│   └── allowed_apps: ["Claude Code", "Cursor"]
│
├── HEALTH
│   ├── allergies: [
│   │     { item: "peanuts", severity: "severe", epipen: true },
│   │     { item: "lactose", severity: "intolerance", note: "Lactaid OK" }
│   │   ]
│   ├── medications: [
│   │     { name: "Lisinopril", dose: "10mg", frequency: "2x daily", prescriber: "Dr. Patel" }
│   │   ]
│   ├── conditions: ["hypertension", "diabetes type 2"]
│   ├── blood_type: "O+"
│   ├── emergency_contact: { name: "Peter", phone: "555-123-4567", relation: "husband" }
│   └── insurance: { provider: "Blue Cross", member_id: "BCX-12345" }
│
├── WORK
│   ├── employer: "TechCorp"
│   ├── title: "Senior Project Manager"
│   ├── team: "Platform Engineering"
│   ├── manager: "Sarah Chen"
│   ├── work_hours: "9am-5pm PT, M-F"
│   ├── tools: ["Jira", "Slack", "Google Workspace"]
│   └── current_projects: [{ name: "API Migration", role: "PM", status: "in_progress" }]
│
├── HOBBIES & INTERESTS
│   ├── hobbies: ["watercolor painting", "soccer", "hiking"]
│   ├── music: ["indie folk", "lo-fi"]
│   ├── books_reading: [{ title: "Project Hail Mary", author: "Andy Weir" }]
│   └── fitness: { type: "yoga", frequency: "3x/week" }
│
├── HOME
│   ├── address: "123 Oak St, San Jose, CA"  (private tier)
│   ├── household: ["Peter", "Jane", "Bill"]
│   ├── pets: [{ name: "Luna", species: "dog", breed: "golden retriever" }]
│   └── vehicles: [{ make: "Toyota", model: "Camry", year: 2022, color: "blue" }]
│
├── CONTACTS
│   ├── (structured contact records with relationship, phone, email, notes)
│   └── ...
│
└── AGENT PREFERENCES
    ├── response_style: "concise"
    ├── share_level_default: "network"
    ├── auto_archive_days: 90
    ├── allowed_query_topics: ["schedule", "work", "general"]
    └── blocked_query_topics: ["finances", "legal"]
```

## Temporal Versioning

Every field change creates a version record. The current value is always the latest version.

```python
class PersonalDataField:
    id: uuid
    owner_id: uuid
    category: str           # "self", "health", "work", etc.
    field_key: str           # "diet", "allergies", "employer"
    current_value: json      # The latest value
    tier: str                # "public" | "network" | "private"
    network_ids: list[uuid]  # Which networks can see this field
    created_at: datetime
    updated_at: datetime

class PersonalDataVersion:
    id: uuid
    field_id: uuid           # FK → PersonalDataField
    value: json              # The value at this point in time
    previous_value: json     # What it was before
    changed_at: datetime
    changed_by: str          # "user" | "agent_suggestion" | "import"
    reason: str | None       # "Updated diet preference"
    is_current: bool         # True for latest version
```

### Example: Diet Change

```
PersonalDataField:
  category: "self"
  field_key: "diet"
  current_value: "pescatarian"
  updated_at: 2026-06-15

PersonalDataVersion history:
  [0] value: "omnivore"      changed_at: 2025-01-01  reason: "initial setup"
  [1] value: "vegetarian"    changed_at: 2026-03-10  reason: "went vegetarian"
  [2] value: "pescatarian"   changed_at: 2026-06-15  reason: "added fish back"  ← current
```

When someone asks "Is Sasha vegetarian?", the agent says:
> "Sasha is currently pescatarian (as of June 2026). She was vegetarian before that."

The agent has temporal context. It doesn't just know the current value — it knows the history.

## How This Relates to Capsules

Capsules and structured fields serve different purposes:

| | Structured Fields | Capsules |
|---|---|---|
| **What** | Factual data points | Rich narrative knowledge |
| **Example** | `allergies: ["peanuts"]` | "Grandma Rose's full evening care routine with medication timings, machine settings, and emergency procedures" |
| **Dedup** | Automatic (one canonical value per field) | Manual/agent-suggested (embedding similarity) |
| **Versioning** | Built-in (every change tracked) | Manual (user updates capsule) |
| **Schema** | Defined categories + field types | Free-form with type hints (memory, skill, etc.) |
| **Scale** | ~100-500 fields per user (manageable) | 100-10,000 capsules (needs organization) |
| **Agent use** | Quick lookups ("what's their diet?") | Deep context ("explain the care routine") |

**The two work together:**
- Structured fields = **fast facts** (diet, allergies, schedule, contacts)
- Capsules = **deep knowledge** (procedures, skills, memories, stories)

When the agent answers a query, it:
1. Pulls relevant **structured fields** for factual grounding
2. Pulls relevant **capsules** via semantic search for rich context
3. Synthesizes both into a response

## Solving the 3000+ Capsule Problem

### 1. Promote Facts to Structured Fields
When a capsule contains a simple fact ("Bill is lactose intolerant"), the agent suggests promoting it to a structured field (`health.allergies`). The capsule can be archived — the field is the source of truth.

### 2. Auto-Categorize on Creation
When a user creates a capsule, the agent:
- Extracts structured data points → suggests creating/updating fields
- Assigns category tags automatically
- Checks for duplicates via embedding similarity
- Links to related capsules

### 3. Smart Views Instead of Folders
```
My Knowledge
├── Quick Facts (structured fields grouped by category)
│   ├── Health (12 fields)
│   ├── Work (8 fields)
│   └── Self (15 fields)
│
├── Deep Knowledge (capsules)
│   ├── All (142 capsules)
│   ├── Recently Updated (12)
│   ├── Needs Review (5)        ← freshness alerts
│   ├── By Type: Procedures (8)
│   ├── By Type: Memories (45)
│   └── By Network: Johnsons (23)
│
└── Suggestions
    ├── Merge candidates (3 groups)
    ├── Promote to fields (7 capsules)
    └── Stale data (4 capsules)
```

### 4. Agent-Assisted Cleanup
The private inbox channel sends periodic suggestions:
- "You have 5 capsules mentioning grandma's medication. Want me to extract the dosages into structured health fields and merge the capsules into one procedure?"
- "Your diet field says 'pescatarian' but a capsule from March says 'vegetarian'. I've already updated the field — should I archive the old capsule?"
- "These 3 schedule capsules are all past their dates. Archive them?"

## Conflict Resolution

When the agent detects a conflict (field value vs capsule content, or two capsules disagreeing):

```python
class DataConflict:
    id: uuid
    owner_id: uuid
    conflict_type: "field_vs_capsule" | "capsule_vs_capsule" | "field_outdated"

    # What's conflicting
    field_id: uuid | None
    capsule_ids: list[uuid]

    # The values
    current_value: json       # What the system currently says
    conflicting_value: json   # What contradicts it
    source_description: str   # "Capsule 'Sasha's Diet' from March says vegetarian"

    # Resolution
    status: "detected" | "user_resolved" | "auto_resolved"
    resolution: json | None   # What was decided
    resolved_at: datetime | None

    created_at: datetime
```

**Resolution strategies:**
1. **Recency wins (default)**: Latest update is canonical. Old values become history.
2. **Authority wins**: If a doctor said "10mg" and a family member said "15mg", prefer the medical professional.
3. **Ask the human**: For ambiguous cases, push to private inbox for resolution.
4. **Never silently overwrite**: Always create a version record. Always notify.

## Tier Mapping for Structured Fields

Each field has its own tier, independent of other fields:

```
SELF
  display_name: public      ← anyone can see your name
  birthday: network          ← only friends/family
  diet: network              ← relevant for meal planning with friends
  allowed_apps: private      ← only your agent needs this

HEALTH
  allergies: network         ← critical for anyone feeding you
  medications: private       ← only you and your agent
  blood_type: private
  emergency_contact: network ← anyone might need this in emergency

WORK
  employer: public           ← on your profile
  title: public
  current_projects: network  ← team members can see
  salary: private            ← never shared
```

## Implementation Path

### Hackathon (now)
- Document the full architecture (this doc)
- Note in demo: "structured fields are the next layer — right now capsules handle everything, but at scale you'd promote facts to versioned fields"

### Post-Hackathon
1. Add `PersonalDataField` and `PersonalDataVersion` models
2. Agent extracts structured data from capsules on creation
3. Temporal versioning on all field updates
4. Conflict detection pipeline
5. Smart views in UI
6. Private inbox notifications for cleanup suggestions
7. Migration tool: bulk-promote existing capsule facts to fields
