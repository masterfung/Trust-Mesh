# TrustMesh Enterprise Use Cases
## Real-world scenarios for auditable knowledge sharing

---

## Use Case 1: Engineering Team Knowledge Transfer

### Scenario
Alice is a principal engineer leaving Acme Corp. Before her departure, her knowledge needs to transfer to the team without losing institutional memory.

### Initial State
```
Alice's Knowledge Vault (encrypted, only Alice can decrypt):
├─ Architecture Decisions (5 capsules)
├─ Infrastructure Knowledge (8 capsules)
├─ Code Review Patterns (3 capsules)
└─ Performance Optimization Techniques (4 capsules)

Total: 20 capsules, not visible to team
Trust tier: "private" (locked to Alice)
```

### The Problem
If Alice just deletes her account:
- Her knowledge is gone (unless legally archived)
- New hire Marcus doesn't know about edge cases in the codebase
- Team rediscovers mistakes already solved
- Six months of productivity loss

### TrustMesh Solution

**Step 1: Import Knowledge to Project Archive**

Alice voluntarily identifies which knowledge the project needs:

```typescript
// Alice runs this (with consent prompts)
const projectKnowledge = await identifyProjectKnowledge(
  aliceUserId,
  "project_apollo",
  {
    categories: ["architecture", "infrastructure", "performance"],
    importance: "high",
    // AI suggests: "These 8 capsules are likely valuable for team"
  }
);

// Alice reviews AI suggestions
const approved = [
  "architecture_microservices_v3",  // Yes, team needs this
  "infrastructure_database_tuning", // Yes, critical
  "performance_caching_strategy",   // Yes
  // "personal_project_notes" - REJECTED (too personal)
];

// Import to project archive
const archive = await importToProjectArchive(aliceUserId, "project_apollo", {
  capsule_ids: approved,
  ownership_transfer: "project",  // Project now owns these
  retention_policy: "permanent"
});
```

**Audit Trail for This Action:**

```
┌────────────────────────────────────────────────┐
│ Knowledge Import to Project Archive            │
├────────────────────────────────────────────────┤
│ Time: 2026-02-12 10:00                        │
│ Grantor: alice (principal_engineer)            │
│ Project: project_apollo                        │
│ Capsules Imported: 3                          │
│ - architecture_microservices_v3                │
│ - infrastructure_database_tuning               │
│ - performance_caching_strategy                 │
│                                               │
│ Action: Consent given ✓                       │
│ Audit Log ID: archive_import_2026_02_001      │
│ Immutable: YES                                │
└────────────────────────────────────────────────┘
```

**Step 2: Team Access During Transition**

Marcus (new engineer) joins the team. When he asks about caching:

```typescript
// Marcus queries the project archive
const response = await queryProjectKnowledge(
  "marcus",
  "How do we optimize cache invalidation?",
  {
    project: "project_apollo",
    audit: true
  }
);

// Response shows:
{
  response: "We use TTL-based invalidation with Redis...",
  sources: [
    {
      capsule_id: "performance_caching_strategy",
      original_owner: "alice",
      imported_at: "2026-02-12",
      import_source: "project_archive",
      version: 1
    }
  ],
  audit_id: "query_2026_02_12_marcus_001"
}
```

**Marcus sees in the UI:**

```
┌───────────────────────────────────────────────┐
│ Q: "How do we optimize cache invalidation?"  │
│                                               │
│ A: "We use TTL-based invalidation with Redis  │
│    cluster, with app-level fallback..."       │
│                                               │
│ Source: Alice's knowledge (imported to       │
│ project) - shared for institutional memory   │
│                                               │
│ [View Audit Log] [Ask Alice (if available)]  │
│                                               │
│ This knowledge was shared as part of         │
│ knowledge transfer on Feb 12, 2026            │
└───────────────────────────────────────────────┘
```

### Compliance Impact
- GDPR: When Alice leaves, her personal knowledge is archived, but the intellectual property stays
- Audit trail: Shows exactly what knowledge was transferred and when
- Accountability: Alice's signature on the transfer is logged

---

## Use Case 2: Cross-Department Knowledge Sharing with Role-Based Access

### Scenario
A healthcare startup (PatientCare) needs to share patient-related knowledge across departments (Medical, Support, Billing) with strict role-based access.

### Initial State

```
PatientCare Organization:
├─ Medical Department
│  ├─ Dr. Sarah (role: Physician, clearance: Secret)
│  └─ Nurse James (role: Clinical Support, clearance: Confidential)
│
├─ Support Department
│  ├─ Support Lead Maya (role: Manager, clearance: Confidential)
│  └─ Support Rep John (role: IC, clearance: Internal)
│
└─ Billing Department
   ├─ Billing Manager Chris (role: Manager, clearance: Confidential)
   └─ Billing Clerk Lisa (role: IC, clearance: Internal)
```

### The Problem

Sarah (physician) creates a capsule: "Diabetes Type 2 Patient Protocols"

Without role-based access:
- Lisa (billing clerk) can see it → HIPAA violation
- John (support rep) should only see general FAQ, not clinical details
- Maya (manager) should see operational aspects but not clinical specifics

### TrustMesh Solution

**Step 1: Define Access Rules in Capsule**

```typescript
const clinicalProtocol = await createCapsule({
  owner_id: "sarah",
  title: "Diabetes Type 2 Patient Protocols",
  content: "...",
  classification: "secret",  // HIPAA PHI

  // Role-based access rules
  access_rules: {
    allowed_roles: {
      "Physician": { can_access: true, can_share: true },
      "Clinical Support": { can_access: true, can_share: false },
      "Manager": {
        can_access: true,
        can_share: false,
        specific_fields_only: ["patient_count", "outcome_metrics"]  // Not PII
      },
      "IC": { can_access: false },
    },

    // Department boundaries
    allowed_departments: ["Medical", "Support"],
    denied_departments: ["Billing", "Legal", "Finance"],

    // Clearance requirement
    required_clearance: "Confidential",  // Lisa has only "Internal" → DENIED

    // Purpose restriction
    purpose_restrictions: [
      "patient_care",
      "operational_support",
      // NOT "cost_reduction" or "billing_optimization"
    ]
  },

  // Audit this closely (HIPAA)
  audit_level: "high",
  breach_notification_required: true
});
```

**Step 2: Access Evaluation**

When John (Support Rep, IC, Internal clearance) tries to access:

```typescript
const access = await checkAccess(johnUserId, clinicalProtocol.id);

// System response:
{
  allowed: false,
  reason: "Insufficient role: IC cannot access Confidential clinical data",
  suggestion: "Ask your manager (Maya) to request access on your behalf",
  escalation_url: "https://trustmesh.../escalate-access-request"
}
```

**Audit Log:**

```
┌────────────────────────────────────────────┐
│ Access Denied (Automatic)                  │
├────────────────────────────────────────────┤
│ Time: 2026-02-12 14:32                    │
│ Requester: john (Support Rep, IC)         │
│ Requested: clinical_protocols_diabetes     │
│ Owner: sarah                               │
│ Reason: Role insufficient                  │
│ Required: Confidential clearance           │
│ Actual: Internal clearance                 │
│                                            │
│ Classification: HIPAA PHI (secret)         │
│ Breach Risk: NONE (blocked at gate)        │
│ Notification: Not needed                   │
│ Immutable: YES                             │
└────────────────────────────────────────────┘
```

When Maya (Manager, Confidential clearance) accesses:

```typescript
const access = await checkAccess(mayaUserId, clinicalProtocol.id);

// System response:
{
  allowed: true,
  reason: "Role permitted: Manager with Confidential clearance",
  restricted_fields: ["patient_names", "ssn", "medical_history_detail"],
  viewable_fields: ["patient_count", "outcome_metrics", "support_needs"],
  audit_log_id: "access_2026_02_12_maya_001"
}
```

**What Maya sees:**

```
Diabetes Type 2 Patient Protocols
(Viewing as Manager - Operational View Only)

Patient Overview:
- Total Patients: 247
- Average Age: 58
- Engagement Rate: 82%

Support Requirements:
- Educational Materials Needed: 5
- Follow-up Call Frequency: Bi-weekly
- Escalation Rate: 12%

[Full Clinical Details Hidden: Only Physicians & Clinical Staff]
[View Audit Log] [Request Full Access]
```

### Compliance Impact
- HIPAA: Enforces minimum necessary access
- Audit: Every access attempt (successful/failed) is logged
- Breach notification: HIPAA violations trigger immediate alerts

---

## Use Case 3: Decision Capsules for Product Teams

### Scenario
A product team needs to record decisions, context, and rationale in a way that survives team changes and enables quick onboarding.

### Initial State

Maria (product manager) needs to document a critical architecture decision:

```
Meeting: Q1 2026 Planning
Attendees: Maria (PM), Alex (Engineering Lead), Sam (Design Lead)
Topic: "Should we refactor our codebase from Monolith to Microservices?"
Duration: 2 hours
Outcome: DECISION MADE
```

### The Problem

Six months later:
- Alex left the company
- New engineer, Priya, joins and asks "Why are we doing this refactor?"
- Nobody remembers the alternatives considered or the tradeoffs
- Priya suggests reverting to monolith (previously rejected for good reasons)
- Meeting happens again, wasting 2 hours

### TrustMesh Solution

**Step 1: Create Decision Capsule**

```typescript
const decision = await createDecisionCapsule({
  owner_id: "maria",
  title: "Refactor to Microservices - Q1 2026 Decision",
  capsule_type: "decision",
  tier: "network",
  network_ids: ["product_team", "engineering_team"],

  // Decision details
  decision: {
    statement: "Adopt microservices architecture to enable independent scaling and team autonomy",

    alternatives_considered: [
      {
        name: "Keep monolith, add caching layer",
        why_rejected: "Caching doesn't solve organizational scaling bottleneck. Two teams can't deploy independently."
      },
      {
        name: "Partial monolith refactor (only payment service extracted)",
        why_rejected: "Doesn't address core issue: 15+ features competing for shared database. Half measures = ongoing pain."
      }
    ],

    rationale: "Current monolith causes deployment conflicts. Engineering team grows to 20+ people. Payment service needs 3x daily deploys, but tied to UI releases. Data team needs direct DB access for analytics.",

    tradeoffs: {
      benefits: [
        "Independent deployment cadence",
        "Teams own their data",
        "Easier to scale payment service"
      ],
      costs: [
        "6-month engineering effort",
        "New operational complexity (monitoring N services)",
        "Potential latency increase on cross-service calls"
      ],
      risk_mitigation: "Start with payment service extraction. Validate benefits. Then expand."
    }
  },

  // Meeting context
  meeting: {
    date: "2026-01-15",
    attendees: ["maria", "alex", "sam"],
    transcript_url: "slack://channels/product/threads/1234567890"
  },

  // Action items with accountability
  action_items: [
    {
      item: "Design payment service API",
      owner: "alex",
      due_date: "2026-02-01",
      status: "completed",
      completion_date: "2026-02-01"
    },
    {
      item: "Spike: Database replication strategy",
      owner: "alex",
      due_date: "2026-02-15",
      status: "in_progress"
    },
    {
      item: "Stakeholder alignment (CFO, CTO)",
      owner: "maria",
      due_date: "2026-02-01",
      status: "completed"
    }
  ],

  // Related decisions
  related_decisions: [
    {
      decision_id: "decision_2025_11_api_gateway",
      relationship: "depends_on"
    },
    {
      decision_id: "decision_2026_01_monitoring_strategy",
      relationship: "requires"
    }
  ],

  tags: ["architecture", "scaling", "organizational"],
  created_at: "2026-01-15T14:30:00Z"
});
```

**Step 2: Team Access**

When Priya (new engineer) joins six months later:

```typescript
// Priya searches for architecture decisions
const results = await searchCapsules("microservices", {
  type: "decision",
  network: "engineering_team"
});

// Finds the decision capsule
// Clicks it and sees the full context
```

**Priya sees:**

```
┌───────────────────────────────────────────────────────┐
│ Refactor to Microservices - Q1 2026 Decision         │
│ (Decision Capsule)                                    │
├───────────────────────────────────────────────────────┤
│                                                       │
│ DECISION:                                            │
│ Adopt microservices architecture to enable           │
│ independent scaling and team autonomy.               │
│                                                       │
│ ALTERNATIVES CONSIDERED:                             │
│ 1. Keep monolith, add caching layer                 │
│    ❌ Rejected: Doesn't solve organizational scaling │
│       bottleneck                                      │
│                                                       │
│ 2. Partial monolith refactor                        │
│    ❌ Rejected: Half-measures won't work with 20+    │
│       person team                                     │
│                                                       │
│ RATIONALE:                                           │
│ "Current monolith causes deployment conflicts..."    │
│ [Full text]                                          │
│                                                       │
│ TRADEOFFS:                                           │
│ Benefits: ✓ Independent deployment                  │
│           ✓ Teams own data                          │
│           ✓ Easy scaling                            │
│ Costs:    ✗ 6 months engineering                    │
│           ✗ New operational complexity              │
│           ✗ Latency between services                │
│                                                       │
│ MEETING CONTEXT:                                     │
│ Date: Jan 15, 2026                                  │
│ Attendees: Maria (PM), Alex (Eng), Sam (Design)     │
│ Recording: [Link to Slack thread]                   │
│                                                       │
│ ACTION ITEMS:                                        │
│ ✓ Design payment API - Alex (Feb 1) - DONE         │
│ → Spike: DB replication - Alex (Feb 15) - IN PROG   │
│ ✓ Stakeholder alignment - Maria (Feb 1) - DONE     │
│                                                       │
│ RELATED DECISIONS:                                   │
│ → Depends on: API Gateway Architecture (Nov 2025)   │
│ → Requires: Monitoring Strategy (Jan 2026)          │
│                                                       │
│ [View Full Audit Log] [Ask Maria] [Reply]           │
└───────────────────────────────────────────────────────┘
```

Priya can now:
- Understand WHY the decision was made
- See what alternatives were considered
- Learn from the tradeoffs
- Check on action item status
- Trace dependencies to other decisions

### Audit Trail

```
┌────────────────────────────────────────────┐
│ Decision Capsule Access Log                │
├────────────────────────────────────────────┤
│ Created: Jan 15, 2026 (Maria)             │
│ Accessed: Jan 16 (Alex), Jan 17 (Sam),   │
│           Feb 12 (Priya)                  │
│                                            │
│ Latest Access:                            │
│ Time: Feb 12 14:32                       │
│ User: priya (new team member)             │
│ Purpose: Onboarding (inferred)            │
│ Duration: 23 min read                     │
│                                            │
│ All accesses immutable - tamper proof    │
└────────────────────────────────────────────┘
```

---

## Use Case 4: Manager Visibility & Team Knowledge

### Scenario
Sarah is an Engineering Manager overseeing a team of 5. She needs to:
1. Understand what her team knows
2. Identify knowledge silos
3. Plan knowledge sharing initiatives

### The Problem

Without TrustMesh:
- Sarah has no visibility into what knowledge exists
- One person is the "expert" in critical subsystem
- If that person leaves, team is stuck
- No way to measure knowledge distribution

### TrustMesh Solution

**Sarah's Manager Dashboard:**

```
┌────────────────────────────────────────────┐
│ Engineering Team Knowledge Overview        │
├────────────────────────────────────────────┤
│                                            │
│ Team Size: 5 engineers                   │
│ Total Knowledge Capsules: 43              │
│ Shared Capsules: 18 (42%)                │
│ Private Capsules: 25 (58%)               │
│                                            │
│ ⚠️  KNOWLEDGE SILOS DETECTED:             │
│                                            │
│ High Risk (Only 1 person knows):          │
│ • Kubernetes cluster configuration        │
│   Known by: Alice only (1 person)         │
│   Impact: Critical (infra)                │
│   Recommendation: Create shared capsule  │
│                                            │
│ Medium Risk (Only 2 people know):         │
│ • Payment service architecture            │
│   Known by: Bob, Charlie (2 people)       │
│   Impact: High (customer-facing)          │
│                                            │
│ EXPERTISE HEATMAP:                        │
│                                            │
│ Topic          Alice Bob Charlie Dave Eve │
│ Kubernetes     ✓✓✓   •   •         •    • │
│ Payments       •     ✓   ✓         •    • │
│ Frontend       •     •   •         ✓    ✓ │
│ Databases      •     ✓   •         •    • │
│ DevOps         ✓     ✓   •         ✓    • │
│                                            │
│ Legend: ✓ Expert, • Familiar, - Novice  │
│                                            │
│ RECOMMENDATIONS:                          │
│ → Ask Alice to create Kubernetes runbook │
│ → Schedule Bob-Charlie knowledge share on│
│   payment service design                  │
│ → Cross-train Dave on DevOps              │
│                                            │
│ [Generate Report] [Share with Exec Team] │
└────────────────────────────────────────────┘
```

**Sarah initiates knowledge sharing:**

```typescript
// Sarah creates a team initiative
const initiative = await createKnowledgeSharingInitiative({
  name: "Kubernetes Knowledge Sharing",
  description: "Reduce single point of failure on K8s infra",
  owner_id: "sarah",
  team_id: "eng_team_001",

  target_capsules: [
    {
      capsule_id: "k8s_cluster_config",
      current_owner: "alice",
      current_tier: "private",
      target_tier: "network",
      deadline: "2026-03-15"
    }
  ],

  // Track progress
  notifications: {
    notify_alice: true,
    notify_team: true,
    weekly_status: true
  }
});

// Audit log shows:
{
  action: "manager_initiated_knowledge_sharing",
  initiated_by: "sarah",
  target_capsule: "k8s_cluster_config",
  target_owner: "alice",
  purpose: "reduce_single_point_of_failure",
  deadline: "2026-03-15",
  timestamp: "2026-02-12"
}
```

**What Alice sees (notification):**

```
┌────────────────────────────────────────────┐
│ Knowledge Sharing Initiative                │
├────────────────────────────────────────────┤
│                                            │
│ Hi Alice,                                 │
│                                            │
│ Sarah has requested that you share your   │
│ Kubernetes expertise with the team.       │
│                                            │
│ Capsule: "Kubernetes cluster config"      │
│ Current: Private (only you can see)       │
│ Requested: Network (team can see)         │
│ Deadline: March 15, 2026                  │
│                                            │
│ By sharing this knowledge:                │
│ ✓ Reduces bus factor for infra            │
│ ✓ Enables faster onboarding               │
│ ✓ Supports team autonomy                  │
│                                            │
│ Your knowledge will:                      │
│ • Still be encrypted in your vault        │
│ • Only be visible to your team            │
│ • Show in access logs (who accesses)      │
│ • Remain editable only by you             │
│                                            │
│ [Agree to Share] [Discuss with Sarah]    │
│ [Decline & Explain] [Suggest Alternative] │
└────────────────────────────────────────────┘
```

### Compliance & Governance

This enables:
- **Knowledge risk assessment**: Identify single points of failure
- **Audit trails**: See when managers push for knowledge sharing
- **Team transparency**: Team sees knowledge gaps clearly
- **Accountability**: Metrics on knowledge distribution

---

## Use Case 5: Client Consulting Work with Temporary Access

### Scenario
A consulting firm (TechConsult) helps a client (TechCorp) on a 3-month project. Consultants need access to TechCorp's knowledge, but access should auto-expire.

### Initial Setup

```
TechConsult (consulting firm):
├─ Senior Consultant: Maya
└─ Junior Consultant: Raj

TechCorp (client):
├─ CTO: Alex
├─ Engineer: Beth
└─ Engineer: Charlie
```

### The Solution

**Step 1: Grant Temporary Access**

Alex (CTO) grants TechConsult access to project knowledge:

```typescript
// Grant 3-month project access
const grants = await grantProjectAccess({
  project_name: "Modernize Payment System",
  grantor_id: "alex",
  grantee_ids: ["maya", "raj"],  // Maya and Raj from TechConsult

  // Time-limited
  valid_from: "2026-02-12",
  valid_until: "2026-05-12",  // 3 months
  auto_revoke_on_expiry: true,

  // Scoped capsules
  capsule_ids: [
    "payment_system_architecture",
    "payment_service_api",
    "deployment_process"
  ],

  // Access level
  access_level: "read_only",  // Consultants can't modify

  // Audit heavily
  audit_level: "high",
  notify_on_access: true,  // Alex gets notifications

  // Purpose tracking
  purpose: "Modernization engagement",
  expected_access_rate: "frequent"  // For anomaly detection
});
```

**Step 2: Maya (Senior Consultant) Accesses Knowledge**

```typescript
const result = await queryWithTemporaryAccess(
  "maya",
  "alex",  // Alex owns the knowledge
  "How does the current payment system handle retries?",
  {
    project: "modernize_payment_system",
    grant_id: grants[0].id
  }
);

// Audit log shows:
{
  requester: "maya",
  purpose: "project_access_temporary",
  access_grant_id: "grant_2026_02_001",
  capsules_accessed: ["payment_system_architecture"],
  expires_in: "89 days",  // Countdown to auto-revocation
  timestamp: "2026-02-12T14:32:00Z"
}

// Alex receives notification:
// "Maya accessed 'payment_system_architecture' at 14:32 (Project: Modernize Payment)"
```

**Step 3: Access Expires Automatically**

May 12, 2026 at 00:00:

```typescript
// Auto-triggered by system
async function revokeExpiredAccess(grantId: string) {
  const grant = await getAccessGrant(grantId);

  if (grant.valid_until <= Date.now()) {
    // Revoke access
    await revokeAccessGrant(grantId);

    // Notify all parties
    await notifyUser(grant.grantor_id, {
      type: "access_expired",
      title: "Temporary project access expired",
      content: `Access for ${grant.grantee_id} expired on ${grant.valid_until}`,
    });

    await notifyUser(grant.grantee_id, {
      type: "access_expired",
      title: "Project access expired",
      content: "Your access to TechCorp's project knowledge has expired. Contact Alex if you need extension.",
    });

    // Log revocation
    await logAccessRevocation({
      grant_id: grantId,
      reason: "automatic_expiry",
      timestamp: Date.now(),
    });
  }
}
```

**May 12, 2026 - Maya Tries to Access Again:**

```typescript
const result = await queryWithTemporaryAccess(
  "maya",
  "alex",
  "Quick question about retry logic",
  { grant_id: "grant_2026_02_001" }
);

// Response:
{
  error: "Access grant expired",
  grant_id: "grant_2026_02_001",
  expired_at: "2026-05-12",
  days_since_expiry: 0,
  can_request_extension: true,
  contact: "alex@techcorp.com"
}
```

**Alex's Project Summary:**

```
┌──────────────────────────────────────────┐
│ Consultant Access Summary                │
│ Project: Modernize Payment System        │
├──────────────────────────────────────────┤
│ Duration: 3 months (Feb 12 - May 12)    │
│ Consultants: Maya, Raj                   │
│ Capsules Accessed: 3                     │
│                                          │
│ ACCESS STATISTICS:                       │
│ Maya:                                    │
│  • Total accesses: 47                    │
│  • Capsules touched: 2                   │
│  • Most accessed: payment_system_arch... │
│  • Last access: May 11, 16:32           │
│                                          │
│ Raj:                                     │
│  • Total accesses: 12                    │
│  • Capsules touched: 1                   │
│  • Most accessed: deployment_process     │
│  • Last access: May 8, 10:15            │
│                                          │
│ STATUS: Access automatically revoked     │
│ All consultant access is now blocked     │
│                                          │
│ [View Detailed Access Log] [Give Feedback]
│ [Generate Consultant Report]             │
└──────────────────────────────────────────┘
```

---

## Use Case 6: Compliance Audit (SOC2, GDPR)

### Scenario
TrustMesh customer undergoes SOC2 audit. Auditor needs to verify knowledge sharing controls.

### Auditor's Requirements

```
SOC2 Audit Scope:
□ Can we identify all knowledge access?
□ Is access logged immutably?
□ Can we verify who accessed what, when?
□ Are access decisions documented?
□ Can unauthorized access be detected?
□ Is there a break-glass procedure for emergencies?
```

### TrustMesh Supports Audit

**Auditor Uses Audit Export:**

```typescript
// Auditor requests audit export for SOC2
const exportId = await exportAuditTrail({
  organization_id: "trustmesh_customer_001",
  start_date: "2025-11-01",
  end_date: "2026-02-12",
  scope: "soc2_audit",
  format: "json_immutable",
  include_access_logs: true,
  include_consent_records: true,
  include_revocations: true,
  include_failures: true,
  integrity_validation: true,
});

// Returns cryptographic proof of:
// 1. No logs were deleted
// 2. No logs were modified
// 3. Complete chain of all accesses
```

**Auditor Reviews Export:**

```json
{
  "export_id": "audit_export_2026_02_soc2_001",
  "organization": "trustmesh_customer_001",
  "period": {
    "start": "2025-11-01T00:00:00Z",
    "end": "2026-02-12T23:59:59Z",
    "days": 104
  },

  "summary": {
    "total_access_logs": 12847,
    "total_denied": 234,
    "total_allowed": 12613,

    "denial_reasons": {
      "insufficient_trust": 145,
      "classification_mismatch": 56,
      "role_mismatch": 23,
      "other": 10
    },

    "unique_users": 342,
    "unique_capsules": 1823
  },

  "sample_logs": [
    {
      "log_id": "audit_2026_02_12_001",
      "timestamp": "2026-02-12T14:32:15Z",
      "requester_user_id": "user_123",
      "requester_agent_id": "user_123_agent",
      "accessed_capsule_id": "capsule_456",
      "capsule_owner_id": "user_789",
      "access_decision": "ALLOWED",
      "trust_level": "FRIEND",
      "citadel_decision": "ALLOW",
      "audit_hash": "sha256:abc123...",
      "immutable": true
    }
  ],

  "integrity_validation": {
    "signature": "rsa_signature_of_all_hashes",
    "verified_at": "2026-02-12T15:00:00Z",
    "status": "VALID - No tampering detected"
  },

  "access_denied_sample": [
    {
      "timestamp": "2026-02-01T10:15:00Z",
      "requester": "user_999",
      "tried_to_access": "capsule_secret_001",
      "owner": "user_111",
      "denial_reason": "Classification: secret, Clearance: internal",
      "action_taken": "Access blocked + logged"
    }
  ]
}
```

**Auditor's Finding:**

```
✓ CC7.2 System Monitoring: COMPLIANT
  - All access attempts logged
  - Immutable audit trail
  - No deletion capability
  - Integrity verified

✓ CC8.1 Change Management: COMPLIANT
  - All capsule updates tracked
  - Version history maintained
  - Who, when, what captured

✓ CC9.2 Access Controls: COMPLIANT
  - Trust-based access control
  - Role-based enforcement
  - Denied accesses logged
  - Break-glass procedure documented
```

---

## Summary

These six use cases demonstrate how TrustMesh's auditable knowledge sharing enables:

1. **Knowledge preservation** across team transitions
2. **Compliance** with healthcare, financial regulations
3. **Organizational learning** through decision documentation
4. **Management visibility** into team knowledge distribution
5. **Secure temporary access** with auto-expiration
6. **Audit-ready systems** for SOC2, GDPR, HIPAA

Each scenario shows:
- How knowledge is shared
- What audit trails look like
- How compliance is enforced
- What users see in the UI
- What happens over time

---

**Key Takeaway:**
TrustMesh isn't just a knowledge tool—it's an **organizational memory system** that makes knowledge flow transparent, auditable, and trustworthy.
