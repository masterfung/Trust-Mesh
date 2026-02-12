# Enterprise Knowledge Sharing for AI Agents: Research & Implementation Guide
## For TrustMesh Platform

**Last Updated:** February 2026
**Research Focus:** Auditable, transparent, and compliant knowledge sharing patterns for enterprise AI agents

---

## Executive Summary

Enterprise knowledge sharing requires balancing three critical tensions:

1. **Utility vs. Security**: Agents need knowledge to be useful, but knowledge is often sensitive
2. **Transparency vs. Performance**: Detailed audit logs impact query latency and storage costs
3. **Decentralization vs. Governance**: Teams want autonomy but organizations need compliance

This document synthesizes industry patterns, architectural approaches, and implementable solutions for TrustMesh to serve enterprise/work contexts.

---

## 1. ENTERPRISE KNOWLEDGE SHARING PATTERNS (2025-2026)

### 1.1 Market Analysis: Current Leaders and Emerging Players

#### **Glean (Enterprise AI Search)**

**How It Works:**
- **Semantic Indexing**: Glean crawls enterprise apps (Slack, Jira, Confluence, Salesforce, Google Drive) and creates semantic embeddings
- **Proprietary Trust Model**: Uses source reliability scoring and document freshness metrics
- **Query Resolution**: When users search, Glean ranks results by:
  - Document recency
  - User access permissions (from source systems)
  - Content relevance and semantic similarity
  - Source authority (how often cited internally)

**Knowledge Sharing Model:**
- **No "borrowing"**: Results are shown to the querying user, not shared with their agent
- **Permission Boundary**: Respects native system permissions (if you can't see it in Slack, you can't see it in Glean)
- **Read-Only**: Knowledge isn't copied or stored in user vaults; queries hit source systems in real-time

**Enterprise Pattern to Adopt:**
- Don't copy sensitive data into personal vaults
- Use real-time permission checking against authoritative sources
- Maintain audit trail at query time, not at storage time

---

#### **Notion AI (Workspace Context Sharing)**

**How It Works:**
- **Workspace-Level Scope**: All AI features operate within workspace boundaries (not cross-workspace)
- **Block-Level Granularity**: Each Notion block (page, database, etc.) has separate access controls
- **Agent Context**: Notion's AI builds prompts from:
  - The current page/block user is on
  - Related pages (via linked databases or backlinks)
  - Workspace members with shared access
  - Time-limited context windows (prevents hallucination over stale data)

**Knowledge Sharing Model:**
- **Contextual Scoping**: AI only "sees" what the human user can see in that moment
- **Cross-Document Reasoning**: Links pages together, enabling knowledge graph-like references
- **No Persistent Agent Memory**: Each query is stateless; no capsule concept

**Enterprise Pattern to Adopt:**
- Implement **view-scoped sharing**: Agent's knowledge access = current user's access
- Use **dynamic scope**: Knowledge available changes based on workspace, team, or time
- Avoid persistent copies; reference and fetch on-demand

---

#### **Slack AI (Relevance Ranking in Chat)**

**How It Works:**
- **Channel-Scoped Knowledge**: Slack's AI assistant primarily searches messages and files in channels the user is a member of
- **Thread Context**: Understands conversation threads and builds context from recent messages
- **Implicit Permissions**: If you can read a channel, the AI can incorporate it into responses
- **Freshness Weighting**: Recent messages weighted higher than old ones

**Knowledge Sharing Model:**
- **Implicit Sharing**: No explicit consent needed; if user is in channel, AI uses that channel's knowledge
- **Broadcast Model**: Same answer given to all channel members asking same question
- **Denial of Context**: Private channels/DMs are inaccessible even to workspace admin AI

**Enterprise Pattern to Adopt:**
- Use implicit membership-based sharing (simpler than explicit consent)
- Weight freshness heavily to reduce stale knowledge
- Distinguish between different scope levels: team, channel, DM

---

#### **Microsoft Copilot (Cross-Team Knowledge Boundaries)**

**How It Works:**
- **Tenant-Level Isolation**: M365 Copilot primarily operates within a single Azure AD tenant
- **Role-Based Context**: Copilot's answers depend on user's Microsoft Graph permissions
- **Cross-App Context**: Can access Teams, OneDrive, SharePoint, Outlook data user can access
- **Manager Access Patterns**: Managers can see team members' shared documents, but not private files

**Knowledge Sharing Model:**
- **Hierarchical Permissions**: Copilot respects org hierarchy
  - Manager queries can include team members' docs (but this isn't always shown to the team member)
  - Individual can't access manager's private docs
- **Sensitive Data Boundary**: Enforces Microsoft Information Protection labels
- **Explainability**: Shows which documents/teams contributed to answer

**Enterprise Pattern to Adopt:**
- Implement **role hierarchy** in permission models
- Use **labeled sensitivity levels** (Public, Internal, Confidential)
- Explicitly communicate what data cross-boundaries

---

#### **2025-2026 New Players & Emerging Patterns**

**Key Emerging Trends:**

1. **Knowledge Graph Platforms** (e.g., Y Combinator-backed startups):
   - Building company-wide "who knows what" graphs
   - Mapping expertise as a commodity
   - Enabling serendipitous knowledge discovery
   - Pattern: Explicit user opt-in to "surface my expertise"

2. **Federated Search Platforms** (e.g., enterprise Perplexity competitors):
   - Multiple data sources queried in parallel
   - Per-source access control enforcement
   - Pattern: "Source bias" — users see which sources contributed

3. **AI-Native Document Vaults** (private funded, not yet public):
   - Purpose-built for agent knowledge storage
   - Native support for multiple trust tiers within single document
   - Concept: "Granular capsules" — semantic chunks with independent access

4. **Knowledge Commons Platforms**:
   - Team decides to share decision logs, meeting notes, project outcomes
   - Real-time sync with source systems (Notion, Confluence, Linear)
   - Pattern: "Ingest, deduplicate, distribute"

**Common 2025-2026 Pattern Emerging:**
```
Query → Permission Check → Scope Expansion → Response
                ↓               ↓                 ↓
        Check user's       Find related      Only include
        access in          content via        accessible
        source system      semantic links     knowledge
```

---

## 2. AUDITABLE KNOWLEDGE BORROWING (The Core TrustMesh Problem)

### 2.1 The Knowledge Borrowing Scenario

```
Agent A (Alice) wants to ask Agent B (Bob):
  "What's Bob's recipe for pasta carbonara?"

Expected flow:
1. Alice's agent queries Bob's vault
2. Bob's agent checks: "Do I trust Alice this much?"
3. If yes: Some knowledge flows from B → A
4. Alice's agent now has that knowledge (temporarily or permanently?)
5. Someone asks: "How did Alice know that?" → Full audit trail needed
```

### 2.2 Five Design Decisions for Auditable Borrowing

#### **Decision 1: Reference vs. Copy Model**

**Option A: Copy Model (High Utility, High Risk)**
```typescript
// Agent A borrows knowledge and stores it
Capsule {
  id: "alice_borrowed_pasta_recipe",
  content: "[copy of Bob's recipe]",
  source_capsule_id: "bob_pasta_recipe",
  borrowed_from_user_id: "bob",
  borrowed_at: timestamp,
  borrowed_via_agent_id: "alice_agent",
  access_tier: "private"  // Alice's copy, not Bob's
}

// When Alice deletes her copy, Bob's original unaffected
// When Bob updates, Alice's copy is stale
```

**Option B: Reference Model (High Auditability, Lower Utility)**
```typescript
Capsule {
  id: "alice_borrowed_pasta_recipe",
  content: "[lightweight reference]",
  source_capsule_id: "bob_pasta_recipe",
  borrowed_from_user_id: "bob",
  access_tier: "borrowed"  // Can't be re-shared
}

// Alice's agent fetches Bob's live version on every query
// Changes to Bob's capsule immediately reflected
// Alice can't use this for offline scenarios
```

**Recommendation for TrustMesh:**
- **Default: Reference Model** with **async caching**
  - Agent fetches live version from Bob
  - Caches for 5-minute window (reduces latency)
  - Cache invalidated if Alice's access revoked
  - Explicit "store locally" option for Alice to request

---

#### **Decision 2: Data Residency Strategy**

**Architecture Decision:**
```
┌─────────────────────────────────────────────────────┐
│ TrustMesh Central Authority (never copies data)     │
├──────────────────┬──────────────────┬───────────────┤
│ Bob's Vault      │ Query Logs       │ Policy Cache  │
│ (encrypted at    │ (minimal info)   │ (permissions) │
│  rest with       │                  │               │
│  Bob's key)      │                  │               │
└──────────────────┴──────────────────┴───────────────┘
          ↑                  ↑                  ↑
          └──────────┬───────┴──────┬──────────┘
                     │              │
                  Query Request   Audit Trail
                     │              │
          ┌──────────┴──────────────┴──────────┐
          │ Alice's Agent (in Bob's response)  │
          │ Processes: Bob's capsule content   │
          │ Never stores locally               │
          └───────────────────────────────────┘
```

**Implementation Pattern:**
```typescript
// When Alice queries Bob
async function borrowKnowledge(
  aliceAgentId: string,
  bobUserId: string,
  question: string
): Promise<{ response: string; auditId: string }> {

  // 1. Check permissions (in TrustMesh, not in Bob's system)
  const trust = await getTrustLevel(aliceAgentId, bobUserId);

  // 2. Fetch Bob's capsules (doesn't copy, just reads)
  const bobCapsules = await fetchCapsules(bobUserId, {
    accessLevel: trust.tier,
    maxAge: trust.dataFreshnessPolicy,
    // Important: no decryption without Bob's consent
  });

  // 3. Log the access (BEFORE using data)
  const auditEntry = await logAccess({
    requester: aliceAgentId,
    resource_owner: bobUserId,
    capsules_accessed: bobCapsules.map(c => c.id),
    decision: "allowed",
    timestamp: Date.now(),
  });

  // 4. Alice's agent uses knowledge, but doesn't store
  const response = await aliceAgent.query(
    question,
    {
      context: bobCapsules,  // Temporary context only
      capsuleSourceMap: new Map([
        [capsule.id, { owner: bobUserId, borrowed: true }]
      ])
    }
  );

  // 5. Return response + pointer to audit
  return {
    response: response.text,
    auditId: auditEntry.id,
    sourceAttribution: bobCapsules.map(c => ({
      capsule_id: c.id,
      owner: bobUserId
    }))
  };
}
```

**Data Residency Rules:**
- Bob's encrypted vault stays on Bob's secure storage
- Query results flow through TrustMesh temporarily
- Alice's agent processes data in-memory, doesn't persist
- Audit logs kept in central system (minimal PII)

---

#### **Decision 3: Revocation and Cascading Updates**

**The Hard Problem:**
> If Bob updates his "Secret Pasta Recipe" capsule after Alice's agent borrowed it, what happens to Alice's response that incorporated that knowledge?

**Solution: Capsule Versioning + Reference Invalidation**

```typescript
interface CapsuleVersion {
  capsule_id: string;
  version: number;
  content: string;
  hash: string;  // Hash of content for change detection
  created_at: timestamp;
  references: {
    agent_id: string;
    query_id: string;
    borrowed_at: timestamp;
  }[];
}

// Bob updates his capsule
await updateCapsule("bob_pasta_recipe", {
  content: "New recipe (I discovered soy sauce helps!)",
  version: 2
});

// TrustMesh detects change
const changes = await detectCapsuleChanges(
  "bob_pasta_recipe",
  from_version: 1,
  to_version: 2
);

// For each reference, decide action
for (const ref of capsule.references) {
  if (changes.semantic_similarity < 0.7) {
    // Major change detected
    await invalidateReference(ref.agent_id, ref.query_id, {
      reason: "Source capsule significantly updated",
      action: "notify_agent"  // Alert Alice's agent
    });
  }
}

// Alice's agent receives notification:
// "Your response to 'pasta recipe' might be stale.
//  Source was updated. Do you want to re-query?"
```

**Revocation Scenarios:**

| Scenario | Action |
|----------|--------|
| Bob deletes the capsule | Soft-delete: mark capsule as archived, don't allow new borrows, but keep references for 30 days (audit trail) |
| Bob changes access tier from "network" to "private" | Revoke all non-direct-connection borrows; notify agents who used it |
| Bob revokes Alice's connection | New borrows blocked immediately; existing references marked with revocation timestamp |
| Alice's agent is deleted | Purge all references from Alice's agent to Bob's capsules |
| Alice's trust tier downgraded | Revoke access to capsules that require higher tier |

**UI for Transparency:**
```
┌─────────────────────────────────────────┐
│ Alice's Query History                   │
├─────────────────────────────────────────┤
│                                         │
│ Q: "Best pasta recipe?"                │
│ Answered: Feb 12, 2026, 14:32           │
│                                         │
│ Sources Cited: ✓ Bob's "Carbonara"      │
│                                         │
│ ⚠️  NOTICE: Source updated on Feb 12    │
│              at 15:00 (28 min after     │
│              your query)                │
│                                         │
│ [Re-query] [View source change]         │
│                                         │
└─────────────────────────────────────────┘
```

---

#### **Decision 4: Compliance & Data Governance**

**GDPR Compliance**

| Requirement | Implementation |
|-------------|-----------------|
| **Right to be Forgotten** | When Bob deletes a capsule, all audit entries referencing it are purged within 24 hours (except legal holds). References from Alice are soft-deleted. |
| **Data Portability** | Users can export all capsules and audit logs they own + all queries made about them. Export format: JSON + manifest. |
| **Processing Transparency** | UI shows: "Your agent borrowed from Bob's vault 47 times in Jan 2026, accessing 5 capsules." |
| **Consent Audit Trail** | Every access requires explicit permission (though pre-granted via trust tier). Consent stored separately for 3 years. |

**SOC 2 Compliance**

```
TrustMesh SOC 2 Control: Knowledge Sharing Audit Trail

1. CC7.2 (System Monitoring)
   - Every capsule access logged with: requester, resource, timestamp, decision, outcome
   - Logs encrypted and immutable (write-once)
   - Retention: 7 years for enterprise plans

2. CC8.1 (Change Management)
   - Capsule updates create new version
   - Previous versions accessible for 90 days
   - Update author logged

3. CC9.2 (Access Controls)
   - Trust tiers enforced at query evaluation time
   - Multiple independent verification checks
   - Failed attempts logged and alerted
```

**HIPAA Implications (for healthcare)**

If TrustMesh is used for health data (patient info, treatment notes):

```typescript
// HIPAA-specific rules
interface HIPAAControlledCapsule extends Capsule {
  classification: "PHI" | "PII" | "GENERAL";

  // Special handling
  auditLogging: {
    immutable: true,
    retention: "7_years",
    cannotBeDeleted: true,
  };

  // Minimum necessary access
  borrowingRules: {
    require_explicit_purpose: true,
    allowedPurposes: ["treatment", "billing", "operations"],
    minimalDataRequired: true,  // Only return needed fields
  };

  // Breach notification
  breachNotification: {
    triggerThreshold: "any_unauthorized_access",
    notifyOwner: true,
    notifyUsers: true,  // If user data is in capsule
  };
}

// HIPAA audit trail example
AuditLog {
  id: "hipaa-12345",
  timestamp: "2026-02-12T14:32:00Z",
  agent_id: "alice_agent",
  accessed_resource: "bob_patient_123_record",
  purpose: "treatment",
  outcome: "allowed",
  data_sensitivity: "PHI",
  ip_logged: true,
  device_id_logged: true,
  cannot_be_modified: true,
  cannot_be_deleted: true,
}
```

---

#### **Decision 5: Consent & Transparency UI**

**Pattern: Progressive Disclosure**

```
User Flow:
Alice (agent owner) ← wants → Bob's knowledge

Moment 1: Alice's agent initiates query
┌──────────────────────────────────┐
│ Querying Bob's agent...          │
└──────────────────────────────────┘

Moment 2: Trust evaluation happens
┌──────────────────────────────────────────────┐
│ Trust Level: "Friend" (can access network)   │
│ Requesting: General Knowledge                │
│ ✓ This request is allowed                    │
└──────────────────────────────────────────────┘

Moment 3: Response received
┌──────────────────────────────────────────────────┐
│ A: Here's what I found from Bob's vault:         │
│                                                  │
│ "Pasta Carbonara Recipe" (shared in friends    │
│  network, recipe type, medium freshness)        │
│                                                  │
│ [More details] [Source audit log]               │
│                                                  │
│ Shared with you from: Bob (peter)               │
│ Shared at: Feb 12, 14:32                        │
│ Access level: Network (friends group)           │
│ Can you use this offline? NO (borrowed ref)     │
│ Can you share this with others? NO (protected) │
└──────────────────────────────────────────────────┘
```

**For Bob: Visibility of Borrowing**

```
Bob's Agent Dashboard → Knowledge Sharing Stats

┌────────────────────────────────────────┐
│ Who's Borrowing From You?              │
├────────────────────────────────────────┤
│ Alice (peter)              47 times     │
│ └─ Accessed: 5 capsules               │
│    - Pasta Recipes (12x)              │
│    - Travel Notes (35x)               │
│    Last accessed: 5 min ago           │
│                                       │
│ Jane (jane)                2 times     │
│ └─ Accessed: 1 capsule                │
│    - Meeting Notes                   │
│    Last accessed: 2 days ago          │
│                                       │
│ [View full audit] [Revoke access]     │
└────────────────────────────────────────┘

Click [View full audit]:
┌────────────────────────────────────────┐
│ Detailed Audit: Who Accessed What      │
├────────────────────────────────────────┤
│ Date     | Who     | What      | Via   │
│ Feb 12   | Alice   | Recipes   | Query │
│ Feb 11   | Alice   | Recipes   | Query │
│ Feb 10   | Jane    | Notes     | Query │
│                                        │
│ [Export CSV] [Set alerts]             │
└────────────────────────────────────────┘
```

---

## 3. WORK MEMORY PATTERNS: Structuring Knowledge for Teams

### 3.1 Four Knowledge Structure Models

#### **Model 1: Shared Capsule (Low Isolation)**

```typescript
interface SharedCapsule {
  id: "team_onboarding_2026",
  owner_id: "engineering_team",  // Owned by team, not individual
  capsule_type: "procedure",
  title: "Engineering Onboarding Checklist",
  content: "...",

  // Key: Multiple owners/editors
  editors: ["alice", "bob", "charlie"],

  // Key: One source of truth
  last_updated_by: "alice",
  last_updated_at: "2026-02-12",
  version: 42,

  // Shared to everyone in team network
  tier: "network",
  network_ids: ["eng_team"],
}

// Problem: Who's responsible for accuracy?
// Solution: Version control + change tracking
History {
  capsule_id: "team_onboarding_2026",
  version: 42,
  changed_by: "alice",
  change_summary: "Updated Docker setup steps, added M1 Mac section",
  prev_version: 41,
  diff: [{ path: "Docker setup", added: "M1 sections" }],
}
```

**Use Cases:**
- Team runbooks
- Shared decision logs
- Project documentation
- Standards & best practices

**Risks:**
- Stale information if not maintained
- Conflicting updates
- No individual accountability

---

#### **Model 2: Shared Vault (Medium Isolation)**

```typescript
interface SharedVault {
  id: "eng_team_vault_2026",
  members: ["alice", "bob", "charlie"],
  access_model: "team",  // All members can add capsules

  capsules: [
    {
      id: "vault_capsule_1",
      owner_id: "alice",  // Still individual owner
      title: "Database Migration Guide",
      tier: "private",  // Private to Alice
    },
    {
      id: "vault_capsule_2",
      owner_id: "bob",
      title: "Kubernetes Config Templates",
      tier: "private",
    }
  ]
}

// When Alice queries vault:
const result = await querySharedVault("eng_team_vault_2026", {
  user: "alice",
  query: "How do I deploy to prod?",
  access_filter: {
    // Can see Alice's private capsules (owner)
    // Can see Bob's network capsules (same vault member)
    // Can see Charlie's public capsules
  }
});
```

**Advantages:**
- Maintains individual ownership & accountability
- Each person responsible for their own knowledge quality
- Collective search across owned + shared knowledge
- Natural discovery ("What does Bob know about Kubernetes?")

**Implementation in TrustMesh:**

Add `VaultMembership` concept:

```typescript
interface VaultMembership {
  vault_id: string;
  user_id: string;
  role: "owner" | "member" | "viewer";
  joined_at: timestamp;
  access_permissions: {
    can_add_capsules: boolean;
    can_view_all_capsules: boolean;  // Or member-level filter
    can_invite_others: boolean;
  };
}

// Query resolution includes vault scope
async function queryWithVaultScope(
  userId: string,
  query: string,
  vaultId: string
): Promise<CapsuleResult[]> {
  const membership = await getVaultMembership(userId, vaultId);

  const capsules = await searchCapsules(query, {
    // Include capsules owned by vault members
    owners: membership.vault_members,

    // Respect individual capsule tiers
    // If capsule is "private", only owner can see
    // If capsule is "network", vault members can see
    accessControl: true,
  });

  return capsules;
}
```

---

#### **Model 3: Federated Search (High Isolation)**

```typescript
// Team-wide search without copying capsules

async function federatedSearch(
  userId: string,
  query: string,
  scope: "team_contacts" | "team_members"
): Promise<FederatedResult[]> {

  const results = [];

  // Search Alice's own vault
  results.push(
    ...(await searchOwnVault(userId, query))
  );

  // Search other team members' vaults
  if (scope === "team_contacts") {
    const connections = await getConnections(userId);

    for (const connection of connections) {
      const peerResults = await queryPeer(
        userId,
        connection.peer_user_id,
        query,
        {
          respectTrustLevel: true,
          returnMetadata: true  // Who has knowledge, but not content yet
        }
      );

      results.push(
        ...peerResults.map(r => ({
          ...r,
          source: connection.peer_user_id,
          access_level: getTrustLevel(connection),
          requires_permission: true  // Can fetch if needed
        }))
      );
    }
  }

  return results;
}

// UI shows:
// "Found 12 results. 8 in your vault, 4 from Bob (needs trust check)"
// User clicks on Bob's result → permission check runs → content fetched
```

**Advantages:**
- Maintains strong privacy boundaries
- Content only fetched on-demand
- Metadata search enables discovery without exposure
- Scales to large teams (just metadata, not full content)

**Implementation Pattern:**

```typescript
// Capsule stores searchable metadata separately from content
interface CapsuleWithMetadata {
  // Public metadata (always searchable)
  metadata: {
    id: string;
    title: string;
    type: "memory" | "skill" | "procedure";
    created_by: string;
    created_at: timestamp;
    freshness: "current" | "stale" | "archived";
    category: string;
    tags: string[];
  };

  // Private content (requires access check)
  content: string;  // Only returned after permission check

  // Search-only index
  searchIndex: {
    title_terms: string[];
    tag_terms: string[];
    content_excerpt: string[];  // First 100 chars of content
  }
}

// Query includes two phases:
// Phase 1: Search metadata (no access check)
const metadataMatches = await searchMetadata(query);

// Phase 2: For user-selected results, check access
const fullyAccessibleResults = await Promise.all(
  metadataMatches.map(m =>
    checkAccessAndFetch(m.id, userId)
  )
);
```

---

#### **Model 4: Knowledge Graph (Relationship-Based)**

```typescript
// "Who in the team knows about X?"
interface KnowledgeGraph {
  nodes: {
    // Agent nodes
    { id: "alice_agent", type: "agent", owner: "alice" },

    // Skill/topic nodes
    { id: "kubernetes", type: "skill" },
    { id: "python", type: "skill" },
    { id: "project_apollo", type: "project" },
  };

  edges: [
    // Alice has expertise in Kubernetes
    { from: "alice_agent", to: "kubernetes", weight: 0.95, type: "expertise" },

    // Bob knows about Python
    { from: "bob_agent", to: "python", weight: 0.87, type: "expertise" },

    // Both worked on Project Apollo
    { from: "alice_agent", to: "project_apollo", weight: 0.9, type: "worked_on" },
    { from: "bob_agent", to: "project_apollo", weight: 0.85, type: "worked_on" },
  ];
}

// Query: "Who can help me with Kubernetes?"
const result = await queryKnowledgeGraph("kubernetes");
// Returns: [Alice (0.95), Marcus (0.72), Reyna (0.45)]

// Query: "Who worked on Project Apollo with Alice?"
const result = await queryKnowledgeGraph({
  relationship: "worked_on",
  subject: "project_apollo",
  connected_to: "alice_agent"
});
// Returns: [Bob, Marcus, Reyna]

// Follow-up: Fetch what Bob knows about Project Apollo
const bobApollo = await fetchAgentKnowledge(
  "bob_agent",
  "project_apollo"
);
```

**How to Build:**

```typescript
// Step 1: Extract skills from capsules
async function buildKnowledgeGraph(userId: string) {
  const capsules = await listCapsules(userId);

  const skills = await extractSkillsFromCapsules(capsules, {
    model: "claude-opus-4.6",  // Use LLM to identify skills
    prompt: "What skills/topics does this capsule demonstrate?",
    threshold: 0.7  // Confidence threshold
  });

  // Step 2: Create edges
  for (const skill of skills) {
    await createGraphEdge({
      from: `${userId}_agent`,
      to: skill.name,
      type: "expertise",
      weight: skill.confidence,
      source_capsules: skill.found_in,
    });
  }

  // Step 3: Sync with work context
  // If Alice is on Project Apollo team, create team edge
  const userTeams = await getTeamsForUser(userId);
  for (const team of userTeams) {
    await createGraphEdge({
      from: `${userId}_agent`,
      to: team.name,
      type: "team_member",
      weight: 1.0,
    });
  }
}

// Step 4: Expose in UI
interface AgentProfilePage {
  agent_name: "Alice";
  expertise: [
    { skill: "Kubernetes", confidence: 0.95, capsules: 12 },
    { skill: "Python", confidence: 0.78, capsules: 8 },
  ];
  teams: ["Engineering", "DevOps", "Project Apollo"];
  recentCollaborators: ["Bob", "Marcus"];

  // Button to ask about specific skill
  actions: ["Ask about Kubernetes", "View project collaborators"];
}
```

---

### 3.2 Meeting Notes & Decisions as Capsules

**Problem:** Meeting notes decay in utility over time. By next sprint, nobody remembers who decided what and why.

**Solution: Decision Capsules**

```typescript
interface DecisionCapsule {
  id: "decision_2026_02_12_api_auth",
  capsule_type: "decision",
  owner_id: "team",

  // Decision metadata
  title: "Standardize API Auth on OAuth 2.0 + JWT",
  meeting: {
    date: "2026-02-12",
    attendees: ["alice", "bob", "charlie"],
    transcript_url: "slack://channels/eng/threads/123",
  },

  decision: {
    statement: "Move from custom auth to OAuth 2.0 with JWT",
    alternatives_considered: [
      "Saml 2.0",
      "Improve custom system"
    ],
    rationale: "Reduces security burden, integrates with third-party",
    tradeoffs: "Higher latency on token validation, but worth it",
  },

  action_items: [
    {
      item: "Implement OAuth 2.0 endpoint",
      owner: "bob",
      due_date: "2026-03-12",
      status: "in_progress",
    }
  ],

  // Searchable context
  tags: ["auth", "architecture", "security"],
  related_decisions: [],

  // Immutable audit trail
  created_at: "2026-02-12",
  created_by: "alice",
  last_updated_at: "2026-02-12",
  change_history: []
}

// Decision links
interface DecisionLink {
  from_decision_id: "decision_2026_02_12_api_auth",
  to_decision_id: "decision_2026_03_01_jwt_lib",
  type: "depends_on" | "supersedes" | "related_to",
}

// Later: When Alice's agent is asked about auth:
// "Why did we choose OAuth 2.0?"
// → Finds decision capsule → Returns rationale + context
```

---

### 3.3 Project Context Surviving Team Turnover

**Problem:** When team members leave, their knowledge walks out the door.

**Solution: Project Knowledge Archive**

```typescript
interface ProjectKnowledgeArchive {
  project_id: "project_apollo",
  created_at: "2025-10-01",

  // Ingest knowledge from team members
  knowledge_sources: [
    {
      source_type: "user_vault",
      source_id: "alice",
      status: "active",
      last_synced: "2026-02-12"
    },
    {
      source_type: "shared_channel",
      source_id: "slack://channels/apollo",
      status: "active",
      last_synced: "2026-02-12"
    },
    {
      source_type: "git_repo",
      source_id: "github://trustmesh/apollo",
      status: "active",
      last_synced: "2026-02-12"
    }
  ],

  capsules: [
    {
      id: "apollo_architecture_v3",
      imported_from: "alice_vault",
      imported_at: "2026-02-01",
      type: "skill",
      tier: "project",  // Owned by project, not Alice
    },
    {
      id: "apollo_deployment_process",
      imported_from: "slack://apollo",
      imported_at: "2026-02-01",
      type: "procedure",
      tier: "project"
    }
  ],

  // When Alice leaves:
  ownership_transfer: {
    from_user: "alice",
    to_entity: "project_apollo",
    transfer_date: "2026-02-15",
    retained_capsules: ["apollo_architecture_v3"],  // Project needs this
    archived_capsules: ["alice_personal_notes"],  // Archived for legal hold
  }
}

// Implementation: Smart import that asks consent
async function importVaultToProject(
  userId: string,
  projectId: string
): Promise<ImportReport> {

  const capsules = await listCapsules(userId);

  // AI identifies project-relevant capsules
  const relevantCapsules = await identifyProjectKnowledge(
    capsules,
    projectId,
    {
      prompt: "Which of these would be useful for the team to have access to?"
    }
  );

  // User approves import
  const approved = await userApproveImport(
    userId,
    relevantCapsules.map(c => c.title)
  );

  // Import creates copies (not references) in project archive
  for (const capsule of approved) {
    await createProjectCapsule({
      original_id: capsule.id,
      original_owner: userId,
      project_id: projectId,
      tier: "project",

      // Metadata showing origin
      metadata: {
        imported_from: userId,
        imported_at: timestamp,
        import_type: "user_consent"
      }
    });
  }

  return {
    imported_count: approved.length,
    skipped_count: relevantCapsules.length - approved.length,
    project_now_has_knowledge: true
  };
}
```

---

## 4. TRANSPARENCY IN AI KNOWLEDGE SHARING

### 4.1 Complete Transparency Architecture

**Goal:** Every user can answer "How did my agent use my knowledge today?"

#### **Component 1: Real-Time Access Logs**

```typescript
interface AccessLog {
  id: "log_2026_02_12_123456",
  timestamp: "2026-02-12T14:32:15Z",

  // Who accessed what
  requester: {
    agent_id: "alice_agent",
    user_id: "alice",
    action: "query"
  },

  resource: {
    capsule_id: "bob_pasta_recipe",
    capsule_title: "Carbonara Recipe",
    owner_id: "bob",
    tier: "network"
  },

  // Why and how
  context: {
    question: "What's the best pasta recipe?",
    shared_networks: ["friends_network"],
    trust_level: "FRIEND"
  },

  // Decision
  access_decision: "ALLOWED",
  access_duration_ms: 145,

  // Audit trail
  audit_hash: "hash(all above)",  // Detect tampering
  immutable: true,
  encryption_key_version: 3,
}

// Store logs in append-only format
// Never update, never delete (except GDPR requests)
```

#### **Component 2: Dashboard Showing Access Patterns**

**For Alice (knowledge owner):**

```
Your Knowledge Dashboard

Knowledge I Own: 47 capsules

Who's Accessing My Knowledge?
┌──────────────────────────────────────────┐
│ This Month (February 2026)               │
├──────────────────────────────────────────┤
│ Bob     : 67 accesses                    │
│ Jane    : 12 accesses                    │
│ Marcus  : 3 accesses                     │
│ Others  : 0 accesses                     │
│                                          │
│ Total: 82 accesses this month            │
└──────────────────────────────────────────┘

Top Capsules Being Borrowed
┌──────────────────────────────────────────┐
│ 1. Pasta Recipes         (45 accesses)   │
│ 2. Travel Notes          (22 accesses)   │
│ 3. Meeting Notes Jan     (10 accesses)   │
│ 4. Kubernetes Guide      (5 accesses)    │
└──────────────────────────────────────────┘

Recent Access Activity
┌──────────────────────────────────────────┐
│ Time  | Who | What        | Status       │
├──────────────────────────────────────────┤
│ 14:32 | Bob | Pasta Rec.  | ✓ Allowed    │
│ 14:15 | Bob | Travel     | ✓ Allowed    │
│ 13:50 | Jane| Meeting    | ✓ Allowed    │
│ 12:30 | ... | ...        | ...         │
│                                        │
│ [See Full Log] [Export CSV]            │
└──────────────────────────────────────────┘

Alert Settings
□ Notify me when someone accesses a "private" capsule
□ Weekly summary of access patterns
□ Alert if unusual access detected (e.g., >100 accesses/day)
```

#### **Component 3: Query Response Transparency**

```
User: "What's a good pasta recipe?"

Agent Response:
┌─────────────────────────────────────────┐
│ RESPONSE                                │
├─────────────────────────────────────────┤
│ Based on advice from my network:        │
│                                         │
│ "Carbonara is classic. Use:            │
│  - Guanciale (not bacon)                │
│  - Whole eggs + Pecorino                │
│  - No cream"                            │
│                                         │
│ [More...] [View sources]               │
└─────────────────────────────────────────┘

Click [View sources]:
┌──────────────────────────────────────────┐
│ Sources for This Answer                 │
├──────────────────────────────────────────┤
│ 1. Carbonara Recipe                     │
│    From: Bob (@peter)                   │
│    Trust: Friend network                │
│    Accessed: Feb 12, 14:32              │
│    [Full capsule] [Audit log]          │
│                                         │
│ 2. Pasta Techniques                     │
│    From: Marcus (@marcus)               │
│    Trust: Public                        │
│    Accessed: Feb 12, 14:31              │
│    [Full capsule] [Audit log]          │
│                                         │
│ 3. Your Own Notes                      │
│    From: Alice                          │
│    (Your own knowledge)                 │
│    [Full capsule]                       │
└──────────────────────────────────────────┘

Click [Audit log]:
┌──────────────────────────────────────────┐
│ Access Audit Log                        │
├──────────────────────────────────────────┤
│ Log ID: log_2026_02_12_123456           │
│ Time: 2026-02-12 14:32:15               │
│ Requester: alice_agent                  │
│ Accessed: bob_pasta_recipe              │
│ Question: "What's a good pasta...?"     │
│ Decision: ALLOWED                       │
│ Reason: Friend trust tier               │
│ Duration: 145ms                         │
│ Citadel Check: PASS                     │
│                                         │
│ [Details] [Report as abuse]             │
└──────────────────────────────────────────┘
```

---

### 4.2 Consent Flows for Sensitive Sharing

**Pattern: Just-In-Time Consent**

```typescript
interface ConsentRequest {
  id: "consent_req_2026_02_12_001",

  requester: {
    agent_id: "alice_agent",
    user_id: "alice",
  },

  resource_owner: {
    user_id: "bob",
  },

  resource: {
    capsule_id: "bob_health_data",
    sensitivity: "HIGH",  // HIPAA, health data
    classification: "PHI"
  },

  question: "What medications are you taking?",

  purpose: "personal_knowledge",  // vs. professional_work

  trust_context: {
    relationship: "spouse",
    existing_access: false,
    requested_access_level: "private"
  },

  // Consent decision
  status: "pending",
  decision: null,
  decided_by: null,
  decided_at: null,

  // If denied, why
  denial_reason: null,

  // Audit trail
  created_at: timestamp,
  created_by_system: "trustmesh_v1",
}

// UI for Bob (resource owner) receiving consent request:
┌─────────────────────────────────────────────┐
│ Consent Request From Alice                 │
├─────────────────────────────────────────────┤
│                                             │
│ Your Agent Alice is asking permission to   │
│ access your "Medications" capsule          │
│ (Sensitive Health Data)                   │
│                                             │
│ Question: "What medications are you       │
│            taking?"                       │
│                                             │
│ Relationship: Spouse (trusted)             │
│                                             │
│ ⚠️  This is sensitive health information   │
│                                             │
│ [ALLOW ONCE]                               │
│ [ALLOW ALWAYS from Alice]                  │
│ [DENY]                                     │
│ [ASK ALICE TO CLARIFY WHY]                 │
│                                             │
│ [Privacy Settings] [Report as abuse]       │
└─────────────────────────────────────────────┘
```

**For Health/Financial Data:**

```typescript
// Require explicit consent per access, not blanket approval
interface SensitiveDataAccess {
  classification: "HIGH_SENSITIVITY",

  consent_type: "per_access",  // Not "once approved, always allowed"

  // Require specific purpose
  allowed_purposes: {
    medical_emergency: true,
    treatment_planning: true,
    casual_sharing: false,
  },

  // Expiration
  consent_expires_after: {
    duration: 24,  // hours
    unit: "hours"
  },

  // Audit trail must be stronger
  audit_retention: "7_years",  // vs. 2 years for normal data

  // Breach notification
  breach_notification: {
    immediate: true,
    notify_owner: true,
    notify_regulatory: true,  // HIPAA, etc.
  }
}
```

---

## 5. ROLE-BASED KNOWLEDGE ACCESS IN WORK NETWORKS

### 5.1 Access Model: Beyond Simple Network Membership

**Current State (Simple):**
```
Alice ←→ Bob ←→ Charlie

Alice can see:
- Her own capsules
- Capsules in networks she's part of
```

**Enhanced State (Work-Ready):**

```
┌─────────────────────────────────────────────────────────┐
│ Role-Based Access Control (RBAC) for Capsules         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Dimension 1: ROLE                                      │
│ ├─ IC (Individual Contributor)                        │
│ ├─ Manager                                             │
│ ├─ Director                                            │
│ └─ C-Suite                                             │
│                                                         │
│ Dimension 2: DEPARTMENT                                │
│ ├─ Engineering                                        │
│ ├─ Product                                             │
│ ├─ Sales                                               │
│ └─ HR                                                  │
│                                                         │
│ Dimension 3: PROJECT                                   │
│ ├─ Project Apollo                                     │
│ ├─ Project Hermes                                     │
│ └─ [Temporary project access expires 2026-03-30]     │
│                                                         │
│ Dimension 4: SENSITIVITY LEVEL                         │
│ ├─ Public                                              │
│ ├─ Internal                                            │
│ ├─ Confidential                                        │
│ ├─ Secret                                              │
│ └─ [Classification assigned at capsule creation]      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### **Example: Manager Access vs. IC Access**

```typescript
// Alice is IC in Engineering
const aliceRole = {
  title: "Engineer",
  department: "Engineering",
  reporting_to: "bob",  // Bob is manager
  clearance_level: "Confidential"
};

// Bob is Manager in Engineering
const bobRole = {
  title: "Engineering Manager",
  department: "Engineering",
  manages: ["alice", "charlie"],
  clearance_level: "Secret"
};

// Capsule shared by HR
const hrCapsule = {
  id: "salary_ranges_2026",
  tier: "internal",
  classification: "Confidential",

  access_rules: {
    // Anyone can see?
    public: false,

    // Only certain roles?
    allowed_roles: ["manager", "director", "c_suite", "hr"],

    // Only certain departments?
    allowed_departments: ["all"],  // HR shares org-wide

    // Only certain clearance levels?
    required_clearance: "Confidential",
  }
};

// When Alice tries to access salary_ranges_2026:
const access = await checkAccess(aliceId, hrCapsule) {
  // Alice is Engineer, not Manager → DENIED
  // Returns: "You don't have access to this capsule.
  //           Managers can see salary information."
  // Alice can REQUEST access from her manager
}

// When Bob tries to access:
const access = await checkAccess(bobId, hrCapsule) {
  // Bob is Manager → ALLOWED
  // Returns: Capsule content
}
```

#### **Pattern: Temporary Project-Based Access**

```typescript
interface TemporaryAccessGrant {
  capsule_id: "project_apollo_architecture",

  grantee: {
    user_id: "alice",
    granted_by: "project_apollo_lead",
  },

  scope: {
    project_id: "project_apollo",
    duration: {
      start: "2026-02-12",
      end: "2026-03-30",
      expires_automatically: true,
    }
  },

  access_level: "read_only",

  // Audit
  created_at: timestamp,
  audit_trail: true,

  // Notification
  notify_on_expiry: true,
  notify_on_update: true,
}

// Implementation in TrustMesh:
class TemporaryAccessManager {
  async grantAccess(
    userId: string,
    capsuleId: string,
    expiresAt: Date
  ): Promise<AccessGrant> {
    // Create access grant with expiration
    const grant = await createAccessGrant({
      user_id: userId,
      capsule_id: capsuleId,
      expires_at: expiresAt,
    });

    // Schedule automatic revocation
    await scheduleRevocation(grant.id, expiresAt);

    // Notify user
    await notifyUserOfTemporaryAccess(userId, capsuleId, expiresAt);

    return grant;
  }

  async checkAccess(userId: string, capsuleId: string): Promise<boolean> {
    const grants = await getAccessGrants(userId, capsuleId);

    for (const grant of grants) {
      if (grant.expires_at > Date.now()) {
        return true;  // Still valid
      }
    }

    return false;
  }

  async revokeOnExpiry(grantId: string): Promise<void> {
    const grant = await getAccessGrant(grantId);

    // Remove access
    await removeAccessGrant(grantId);

    // Notify user
    await notifyUserOfAccessExpiry(
      grant.user_id,
      grant.capsule_id,
      grant.expires_at
    );

    // Log revocation
    await logAccessRevocation(grantId, "automatic_expiry");
  }
}
```

#### **Pattern: Need-to-Know Basis Sharing**

```typescript
// "I want to share X with Y, but only for this specific purpose"

interface NeedToKnowGrant {
  id: "ntk_2026_02_12_001",

  capsule_id: "client_financial_data",

  // Who gets access and why
  recipient: {
    user_id: "sales_rep_alice",
    department: "Sales",
  },

  grantor: {
    user_id: "cfo",
  },

  // The specific purpose
  purpose: {
    type: "contract_negotiation",
    description: "Need client financials for Q1 contract renewal",
    specific_fields_only: [
      "annual_revenue",
      "growth_rate",
      "profitability"
    ],
    fields_excluded: [
      "internal_cost_structure",
      "salary_data"
    ]
  },

  // Validity
  valid_from: "2026-02-12",
  valid_until: "2026-02-28",

  // Tracking
  access_count: 0,
  audit_logs: [
    { timestamp: "2026-02-12 14:32", action: "accessed" },
    { timestamp: "2026-02-12 15:45", action: "accessed" }
  ],

  // Revocation
  can_revoke_early: true,
  revoked_at: null,
}

// Implementation:
async function grantNeedToKnow(
  capsuleId: string,
  recipientId: string,
  purpose: string,
  expiresAt: Date
): Promise<NeedToKnowGrant> {

  const grant = await createNeedToKnowGrant({
    capsule_id: capsuleId,
    recipient_id: recipientId,
    purpose: purpose,
    expires_at: expiresAt,
  });

  // Create filtered version of capsule
  // that only includes relevant fields
  const filteredCapsule = await filterCapsuleForPurpose(
    capsuleId,
    purpose
  );

  // Grant access to filtered version
  await grantAccess(recipientId, filteredCapsule.id);

  // Notify recipient of access, purpose, and expiration
  await notifyRecipient(
    recipientId,
    `You've been granted access to ${capsule.title} for ${purpose} until ${expiresAt}`
  );

  // Strong audit trail
  await logNeedToKnowGrant(grant);

  return grant;
}
```

---

### 5.2 Multi-Tenant Awareness in Enterprise

**Pattern: Organization Boundaries**

```typescript
interface Organization {
  id: "acme_corp",
  name: "Acme Corporation",

  // Organizational structure
  departments: ["engineering", "sales", "hr", "finance"],

  teams: [
    { id: "eng_backend", name: "Backend", dept: "engineering" },
    { id: "eng_frontend", name: "Frontend", dept: "engineering" },
    { id: "sales_amer", name: "Sales AMER", dept: "sales" }
  ],

  // Data governance
  data_residency: "US-EAST-1",
  compliance_frameworks: ["SOC2", "HIPAA", "GDPR"],

  // Knowledge boundaries
  cross_department_sharing: true,  // Allow sharing across depts
  cross_org_sharing: false,  // Don't allow external sharing
}

// When Alice (Acme) queries Bob (Acme):
async function queryWithOrgBoundary(
  queryingUserId: string,
  targetUserId: string
): Promise<QueryResult> {

  const queryingOrg = await getUserOrganization(queryingUserId);
  const targetOrg = await getUserOrganization(targetUserId);

  if (queryingOrg.id !== targetOrg.id) {
    // Cross-organization query
    // More restrictions apply

    return {
      decision: "denied",
      reason: "Cross-organization queries not permitted",
    };
  }

  // Same organization: proceed
  // But still check department-level rules
  const policy = await getOrgPolicy(queryingOrg.id, {
    query: "can_share_across_departments"
  });

  return await executeQuery(...);
}
```

---

## 6. CONCRETE IMPLEMENTATION PATTERNS FOR TrustMesh

### 6.1 Database Schema Additions

```typescript
// New tables to add to TrustMesh

// 1. Access audit table (immutable, write-once)
CREATE TABLE access_audit_logs (
  id UUID PRIMARY KEY,
  timestamp TIMESTAMP NOT NULL,
  requester_agent_id UUID NOT NULL,
  requester_user_id UUID NOT NULL,
  accessed_capsule_id UUID NOT NULL,
  capsule_owner_id UUID NOT NULL,
  question TEXT,
  trust_level VARCHAR(50),
  access_decision VARCHAR(20),  -- ALLOWED, DENIED
  access_duration_ms INT,
  citadel_decision VARCHAR(20),
  source_networks TEXT[],
  audit_hash VARCHAR(256),  -- For tamper detection
  created_at TIMESTAMP DEFAULT NOW(),

  -- Make immutable
  CHECK (created_at = NOW()),
  INDEX (requester_user_id),
  INDEX (capsule_owner_id),
  INDEX (timestamp)
);

// 2. Capsule versions (track updates)
CREATE TABLE capsule_versions (
  id UUID PRIMARY KEY,
  capsule_id UUID NOT NULL REFERENCES capsules(id),
  version_number INT NOT NULL,
  content TEXT NOT NULL,
  content_hash VARCHAR(256),  -- Detect changes
  changed_by UUID NOT NULL,
  change_summary TEXT,
  created_at TIMESTAMP DEFAULT NOW(),

  UNIQUE (capsule_id, version_number),
  INDEX (capsule_id)
);

// 3. Knowledge borrowing references
CREATE TABLE capsule_references (
  id UUID PRIMARY KEY,
  source_capsule_id UUID NOT NULL REFERENCES capsules(id),
  borrowing_agent_id UUID NOT NULL,
  borrowing_user_id UUID NOT NULL,
  reference_type VARCHAR(20),  -- COPY, REFERENCE, CACHED
  reference_valid_until TIMESTAMP,

  created_at TIMESTAMP DEFAULT NOW(),
  INDEX (source_capsule_id),
  INDEX (borrowing_user_id)
);

// 4. Access grants (for manager/IC distinctions)
CREATE TABLE access_grants (
  id UUID PRIMARY KEY,
  capsule_id UUID NOT NULL REFERENCES capsules(id),
  granted_to_user_id UUID NOT NULL,
  granted_by_user_id UUID NOT NULL,

  -- Role-based
  required_role VARCHAR(100),
  required_department VARCHAR(100),
  required_clearance VARCHAR(50),

  -- Time-limited
  valid_from TIMESTAMP,
  valid_until TIMESTAMP,
  auto_revoke BOOLEAN DEFAULT TRUE,

  -- Sensitivity
  purpose TEXT,
  sensitivity_level VARCHAR(50),

  created_at TIMESTAMP DEFAULT NOW(),
  INDEX (capsule_id),
  INDEX (granted_to_user_id),
  INDEX (valid_until)
);

// 5. Consent records (for high-sensitivity data)
CREATE TABLE consent_records (
  id UUID PRIMARY KEY,
  requester_agent_id UUID NOT NULL,
  requester_user_id UUID NOT NULL,
  resource_owner_id UUID NOT NULL,
  capsule_id UUID NOT NULL REFERENCES capsules(id),

  question TEXT,
  purpose VARCHAR(100),

  -- Decision
  status VARCHAR(20),  -- PENDING, APPROVED, DENIED
  decided_by UUID,
  decided_at TIMESTAMP,
  denial_reason TEXT,

  -- Audit
  created_at TIMESTAMP DEFAULT NOW(),
  expires_at TIMESTAMP,

  INDEX (requester_user_id),
  INDEX (resource_owner_id),
  INDEX (status)
);

// 6. Organization boundaries
CREATE TABLE organizations (
  id UUID PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  data_residency VARCHAR(50),
  compliance_frameworks TEXT[],
  cross_org_sharing_allowed BOOLEAN DEFAULT FALSE,

  created_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN organization_id UUID REFERENCES organizations(id);

// 7. Role definitions (per organization)
CREATE TABLE role_definitions (
  id UUID PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id),
  role_name VARCHAR(100),
  role_level INT,  -- 1=IC, 2=Manager, 3=Director, 4=C-Suite
  clearance_level VARCHAR(50),

  UNIQUE (organization_id, role_name)
);

ALTER TABLE users ADD COLUMN role_id UUID REFERENCES role_definitions(id);
```

### 6.2 API Endpoints to Implement

```typescript
// New endpoints for TrustMesh

// 1. Query with full transparency
POST /api/query-with-audit
{
  from_user_id: string;
  to_user_id: string;
  question: string;
  require_transparency: boolean;  // Return audit info
}
→ {
  response: string;
  audit_id: string;
  sources: { capsule_id, owner, borrowed }[];
  can_share_offline: boolean;
}

// 2. Access logs for user
GET /api/users/{userId}/access-logs
Query params:
  - period: "day" | "week" | "month"
  - direction: "incoming" (who accessed my knowledge) | "outgoing" (I accessed)
→ AccessLog[]

// 3. Knowledge dashboard
GET /api/users/{userId}/knowledge-stats
→ {
  capsules_owned: number;
  capsules_borrowed: number;
  access_this_month: number;
  top_accessed_capsules: Capsule[];
  recent_accessors: { user_id, access_count }[];
}

// 4. Grant/revoke access
POST /api/capsules/{capsuleId}/grant-access
{
  user_id: string;
  access_type: "temporary" | "permanent";
  expires_at?: timestamp;
  reason?: string;
  required_role?: string;
}

DELETE /api/capsules/{capsuleId}/grant-access/{grantId}

// 5. Consent requests
POST /api/consent/request
{
  requester_user_id: string;
  resource_owner_id: string;
  capsule_id: string;
  question: string;
  purpose: string;
}

POST /api/consent/{consentId}/approve
POST /api/consent/{consentId}/deny
{
  reason: string;
}

// 6. Knowledge graph queries
GET /api/knowledge-graph/experts
{
  skill: string;
  organization_id?: string;
}
→ { agent_id, user_id, expertise_level, capsule_count }[]

// 7. Audit export (for compliance)
POST /api/audit/export
{
  start_date: string;
  end_date: string;
  format: "json" | "csv";
  include_content: boolean;
}
→ { export_id, download_url, expires_at }
```

### 6.3 UI Components to Build

```typescript
// Key components for transparency

// 1. Access Log Viewer
<AccessLogViewer
  userId={string}
  direction="incoming"  // or "outgoing"
  period="month"
  onSelectLog={(log) => showAuditDetail(log)}
/>

// 2. Knowledge Stats Dashboard
<KnowledgeStatsDashboard
  userId={string}
  showTopAccessors={true}
  showAccessTrends={true}
  onViewFullLog={() => navigate("/logs")}
/>

// 3. Capsule with Source Attribution
<CapsuleWithSources
  capsule={Capsule}
  sources={[
    { capsule_id, owner, borrowed_at, audit_id }
  ]}
  onClickAudit={(auditId) => showAuditLog(auditId)}
/>

// 4. Consent Request UI (for resource owner)
<ConsentRequestPrompt
  request={ConsentRequest}
  onAllow={() => approveConsent()}
  onDeny={() => denyConsent()}
  onAskClarification={() => requestMoreInfo()}
/>

// 5. Access Grant Manager (for managers)
<AccessGrantManager
  userId={string}
  grants={AccessGrant[]}
  onGrant={(userId, capsuleId, expiresAt) => grantAccess(...)}
  onRevoke={(grantId) => revokeAccess(grantId)}
  showRoleFilter={true}
/>

// 6. Knowledge Graph Explorer
<KnowledgeGraphExplorer
  organization_id={string}
  onSelectExpert={(userId) => viewExpertiseProfile(userId)}
  onQuerySkill={(skillName) => findExperts(skillName)}
/>
```

---

## 7. IMPLEMENTATION ROADMAP FOR STARTUP

### Phase 1: Foundation (Weeks 1-4)
- [ ] Implement access audit table
- [ ] Add audit logging to all query operations
- [ ] Build basic access log viewer in UI
- [ ] Implement capsule versioning system

### Phase 2: Work-Ready (Weeks 5-8)
- [ ] Add role-based access control (RBAC)
- [ ] Implement temporary access grants
- [ ] Add organization/department boundaries
- [ ] Build knowledge stats dashboard

### Phase 3: Compliance (Weeks 9-12)
- [ ] Implement consent flows for sensitive data
- [ ] Add audit export for compliance (SOC2, GDPR)
- [ ] Implement data residency controls
- [ ] Add immutable audit log enforcement

### Phase 4: Advanced (Weeks 13-16)
- [ ] Build knowledge graph extraction
- [ ] Implement AI-driven skill identification
- [ ] Add federated search across team
- [ ] Build knowledge commons platform

---

## 8. KEY DESIGN DECISIONS SUMMARY

| Decision | Recommendation | Rationale |
|----------|---|---|
| Copy vs. Reference | Reference + 5min cache | Maintains Bob's control, reduces stale data |
| Data Residency | No central copy | Bob's vault stays encrypted; TrustMesh never holds plaintext |
| Revocation | Soft-delete + version tracking | Preserves audit trail while respecting user wishes |
| GDPR Compliance | Right to be forgotten = 24h purge | Balance privacy with audit retention |
| Consent Model | JIT consent for HIGH sensitivity | More secure than blanket "approve once" |
| Manager Access | Hierarchy-aware ACL | Managers can see team knowledge, but team can't see theirs |
| Project Context | Import + archive model | Survives team turnover, maintains source attribution |
| Transparency | Every user sees their access logs | Make knowledge flow visible to all parties |

---

## 9. COMPETITIVE POSITIONING

**How TrustMesh differs from incumbents:**

| Feature | Glean | Notion AI | Slack AI | Microsoft Copilot | TrustMesh |
|---------|-------|-----------|----------|-------------------|----------|
| Cross-user knowledge sharing | No | No | No | Limited | Yes |
| Persistent agent memory (capsules) | No | No | No | No | Yes |
| Explicit consent flows | No | No | Implicit | No | Yes |
| Full audit trail visible to users | No | No | No | No | Yes |
| Knowledge graph of expertise | No | No | No | No | Yes |
| Survives team turnover | No | No | No | No | Yes |
| Reference-based (not copied) | Yes | Yes | Yes | Yes | Yes |
| Role-based capsule access | No | Limited | No | Yes | Yes |
| Purpose-based sharing | No | No | No | No | Yes |
| Open protocol (not vendor-locked) | No | No | No | No | Yes |

---

## 10. RESOURCES & FURTHER READING

### Enterprise Knowledge Management
- "The Knowledge-Creating Company" - Ikujiro Nonaka & Takeuchi
- Gartner: "Enterprise Knowledge Management" reports
- Forrester: "Knowledge Work" research

### Privacy & Compliance
- GDPR Articles 6-9 (Lawful basis & consent)
- SOC 2 Trust Service Criteria (CC7-CC9 for audit)
- HIPAA Minimum Necessary Standard
- Data Protection Impact Assessments (DPIA) template

### AI Transparency
- "Explainable AI" - Chapters 3-4 on audit trails
- Anthropic: "Constitutional AI" (for responsible sharing)
- IEEE: "AI Ethics" standards

### Related Platforms
- Glean documentation: https://glean.com/docs
- Notion API: https://developers.notion.com/
- Slack Bolt Framework: https://slack.dev/bolt/
- Microsoft Graph API: https://developer.microsoft.com/en-us/graph

---

## Conclusion

TrustMesh is positioned to solve a critical gap: **auditable, transparent knowledge sharing between AI agents in enterprise contexts**. The reference-based model, combined with comprehensive audit trails, consent flows, and role-based access control, creates a foundation for trustworthy multi-agent systems.

The key to adoption is **making knowledge flow visible** to all parties. Every user should be able to answer:
- "Who accessed my knowledge today?"
- "What knowledge was my agent using?"
- "Why was I denied access to X?"

This transparency builds trust, enables compliance, and creates a more human-centered AI system.

---

**Document prepared for:** Claude Opus 4.6 Hackathon
**TrustMesh Architecture Review**
**Feb 12, 2026**
