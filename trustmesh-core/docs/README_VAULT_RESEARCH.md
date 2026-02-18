# HashiCorp Vault Research & TrustMesh Architecture Mapping

## Documents in This Research Suite

This directory contains the complete research and implementation roadmap for applying HashiCorp Vault's architecture to TrustMesh.

### 1. **VAULT_QUICK_REFERENCE.md** — START HERE
**Purpose**: One-pager cheat sheet for developers.

**Contents**:
- Core Vault primitives (with ASCII diagrams)
- Key hierarchy visualization
- Secrets engines (mount points)
- Policy language (path matching + capabilities)
- Audit logging (fail-safe guarantee)
- Leases & cascading revocation
- Transit engine (encryption-as-a-service)
- Enterprise features summary
- Threat model in-scope/out-of-scope
- Implementation priority matrix
- Quick-start templates

**Use When**: You need a fast reference while coding.

---

### 2. **vault-architecture-mapping.md** — DEEP DIVE
**Purpose**: Comprehensive architecture comparison (2500+ lines).

**Sections**:
1. Executive Summary
2. Vault Core Primitives (with TrustMesh translation):
   - Seal/Unseal (3-tier ceremony for pods)
   - Secrets Engines (capsule/timeline/transit modularization)
   - Policies (deny-by-default ACLs)
   - Audit Logging (tamper-evident records)
   - Leases & TTLs (cascade revocation)
   - Transit Engine (encryption-as-a-service)

3. Enterprise Features (namespaces, Sentinel, replication, HSM)
4. API Surface (REST, CLI, SDKs, Agent sidecar)
5. Threat Model (in-scope vs out-of-scope, trust boundaries)
6. Actionable Architecture Patterns (6 detailed implementations)
7. What Vault Doesn't Do (that AI needs)
8. HCP Vault Pricing Analysis
9. Zig Kernel Implementation Roadmap

**Use When**: You need architectural context or implementing a pattern.

---

### 3. **vault-vs-trustmesh-comparison.md** — SIDE-BY-SIDE TABLES
**Purpose**: Detailed feature comparison with code examples.

**Contents**:
- Overview table (core primitives)
- 6 detailed feature comparisons:
  1. Seal/Unseal ceremony (3-phase TrustMesh)
  2. Secrets engines (modular mount points)
  3. Policy language (HCL parsing, Zig compilation)
  4. Audit logging (fail-safe, immutable)
  5. Leases (parent-child hierarchy, renewal)
  6. Transit engine (key versioning, rotation)

- Threat model comparison (TrustMesh additions)
- Cloud pricing comparison (HCP Vault vs. TrustMesh proposed model)
- Summary table (what to steal from Vault)

**Use When**: Writing detailed specs or presenting to stakeholders.

---

### 4. **vault-implementation-priorities.md** — ACTION PLAN
**Purpose**: Prioritized implementation roadmap with code examples and effort estimates.

**Sections**:
1. Priority 1: Mandatory Audit Logging (6h)
   - Schema, decorator, fail-safe pattern

2. Priority 2: Cascading Token Revocation (4h)
   - Parent-child model, cascade logic

3. Priority 3: Three-Tier Pod Unsealing (8h)
   - Shamir shares, admin ceremony, Zig exports

4. Priority 4: Policy Engine in Zig (10h)
   - HCL parser, path matching, policy checker

5. Priority 5: Transit Engine (5h)
   - Encrypt/decrypt/rotate routes, key versioning

6. Priority 6: Token Renewal & Health Monitor (4h)
   - Periodic renewal, auto-pause stale agents

7. Priority 7: Audit Export (4h)
   - HMAC signing, S3 sync, compliance

8. Priority 8: Pod Replication (8h, Phase 2)
   - Delta sync, failover, consistency

**Includes**:
- Full code examples (Python + Zig)
- Integration points with existing code
- Test cases (count + coverage)
- Effort estimates (hours)
- Recommended implementation order (2-3 weeks)

**Use When**: Starting implementation or planning sprint.

---

## Key Takeaways

### What Makes Vault Enterprise-Grade

1. **Seal/Unseal**: Master key ceremony (Shamir or HSM) prevents unsealing with single point of failure
2. **Deny-by-Default Policies**: Explicit grants with deny override; path matching + capabilities
3. **Fail-Safe Audit**: If audit write fails, operation refused (prevents silent breaches)
4. **Cascading Revocation**: Token hierarchy (parent → children) for cleanup on expiry
5. **Key Rotation Without Re-encryption**: Version IDs in ciphertext, automatic key upgrade
6. **Separation of Concerns**: Independent mount points (KV, Transit, Dynamic Secrets, PKI)

### What TrustMesh Adds (That Vault Lacks)

1. **Semantic Search Over Encrypted Data**: FTS5 indexing without decryption (SQLite)
2. **Trust-Based Sharing** (not just ACL): Dynamic trust resolution at query time
3. **Agent Identity (DIDs)**: Persistent portable identities across pods
4. **Temporal Execution**: Cron-based scheduling, state machines, agent task automation
5. **Cross-Organization Federation**: Multi-pod trust networks with data minimization

### Implementation Roadmap (50 hours total)

**Week 1** (14h):
- Audit logging (mandatory, fail-safe)
- Token cascade revocation
- Token renewal + health monitor

**Week 2** (13h):
- Three-tier pod unsealing
- Transit engine

**Week 3** (10h):
- Policy engine (Zig kernel)

**Week 4** (12h):
- Audit export (compliance)
- Pod replication (Phase 2)

**MVP** (Security-focused, 15h):
- Audit logging + cascade revocation + transit engine

---

## Research Methodology

This research combined:
1. **HashiCorp Vault Official Docs** (architecture, API, security model, pricing)
2. **Enterprise Feature Analysis** (namespaces, Sentinel, replication, HSM)
3. **Threat Model Mapping** (in-scope vs out-of-scope attacks)
4. **Cloud Pricing Strategy** (HCP Vault Secrets → Dedicated migration; TrustMesh model)
5. **TrustMesh Codebase Review** (models.py, trust.py, gossip.py, timeline.zig)
6. **Actionable Patterns** (code templates, Zig kernel integration, Python FFI)

---

## Sources

**Official Documentation**:
- [Vault Seal/Unseal](https://developer.hashicorp.com/vault/docs/concepts/seal)
- [Vault Policies](https://developer.hashicorp.com/vault/docs/concepts/policies)
- [Vault Audit Logging](https://developer.hashicorp.com/vault/docs/audit)
- [Vault Leases](https://developer.hashicorp.com/vault/docs/concepts/lease)
- [Vault Security Model](https://developer.hashicorp.com/vault/docs/internals/security)
- [Vault HTTP API](https://developer.hashicorp.com/vault/api-docs)
- [HCP Vault Pricing](https://cloud.hashicorp.com/products/vault/pricing)

**Research Articles**:
- [Vault Enterprise Features Comparison](https://infisical.com/blog/hashicorp-vault-pricing)
- [Sentinel Policy-as-Code](https://developer.hashicorp.com/vault/docs/enterprise/sentinel)
- [HSM Integration for FIPS Compliance](https://developer.hashicorp.com/vault/docs/enterprise/hsm)

**Project Context**:
- `/Users/jh/Code/mighty/claude-opus-hackathon/CLAUDE.md` (project instructions)
- `/Users/jh/.claude/projects/.../memory/MEMORY.md` (project memory/timeline kernel)

---

## How to Use This Research

### For Architecture Review
1. Start: `VAULT_QUICK_REFERENCE.md` (5 min overview)
2. Deep dive: `vault-architecture-mapping.md` (30 min detailed read)
3. Comparison: `vault-vs-trustmesh-comparison.md` (evaluate fit)

### For Implementation
1. Start: `vault-implementation-priorities.md` (pick next priority)
2. Code: Copy code examples from priority section
3. Reference: Use `VAULT_QUICK_REFERENCE.md` for patterns during coding
4. Context: Return to mapping docs if design questions arise

### For Stakeholder Presentations
1. Use: `VAULT_QUICK_REFERENCE.md` ASCII diagrams
2. Show: Threat model comparison (in-scope/out-of-scope)
3. Reference: Cloud pricing analysis (position vs. Vault)
4. Discuss: Implementation roadmap (50h over 4 weeks)

### For Security/Compliance Reviews
1. Study: Threat model section (vault-architecture-mapping.md)
2. Examine: Audit logging design (priority 1)
3. Review: Fail-safe guarantees (audit + policy)
4. Verify: Cascade revocation (token lifecycle)

---

## Next Steps

### Immediate (Today)
1. Read `VAULT_QUICK_REFERENCE.md` (10 min)
2. Review `vault-implementation-priorities.md` (priority 1 code)
3. Decide: Start with Priority 1 (audit logging) or Priority 5 (transit)?

### Short-term (This Week)
1. Implement Priority 1 + 2 (audit + cascade revocation) → 10 hours
2. Create tests (audit decorator, cascade scenarios)
3. Integrate with existing routes (capsule read, agent execution)

### Medium-term (Weeks 2-4)
1. Implement Priority 3 + 4 (unsealing ceremony, policy engine)
2. Zig kernel extensions (policy checker)
3. Cross-pod federation hardening (cascade revocation across pods)

---

## Questions? Notes?

**For architectural questions**:
- See `vault-architecture-mapping.md` section on specific pattern

**For implementation details**:
- See `vault-implementation-priorities.md` code examples

**For quick lookup**:
- See `VAULT_QUICK_REFERENCE.md` one-liners + templates

---

**Research Generated**: 2026-02-17
**Scope**: HashiCorp Vault core architecture → TrustMesh mapping
**Format**: 5 markdown documents, ~5000 lines, production-ready
**Status**: Ready for implementation
