# TrustMesh Documentation

Trust-aware knowledge sharing for AI agents.

## Architecture & Design

| Document | Description |
|----------|-------------|
| [Knowledge Sharing Protocol](./knowledge-sharing-protocol.md) | **Start here.** How sharing, discovery, permissioning, revocation, and UCAN authorization work end-to-end |
| [Protocol Landscape](./protocol-landscape.md) | How A2A, MCP, AgentMail, and emerging standards compare — and where TrustMesh fits |
| [Trust Architecture](./trust-architecture.md) | Three-tier trust model, trust resolution algorithm, capability tokens, policy engines |
| [Security Model](./security-model.md) | Encryption (AES-256-GCM), authentication (Argon2id), Citadel scanning, threat model, compliance |
| [Agent Discovery](./agent-discovery.md) | How agents find and authenticate each other, A2A agent cards, human-mediated discovery |
| [Knowledge Capsules](./knowledge-capsules.md) | Capsule types, storage architecture, semantic retrieval (ChromaDB), freshness and data rot |
| [Solicitation Protocol](./solicitation-protocol.md) | Abuse prevention, agent escalation (RESPOND/SOLICIT/DELEGATE), work sharing, dedup, scale |

## Reference

| Document | Description |
|----------|-------------|
| [API Reference](./api-reference.md) | All REST endpoints: auth, users, connections, networks, capsules, queries, graph |
| [Demo Scenarios](./demo-scenarios.md) | The 7 demo scenarios with the Johnson family, including the 3-minute video script |

## Quick Links

- **Backend**: `trustmesh-core/` (Python + FastAPI, port 8000)
- **Frontend**: `trustmesh-ui/` (Next.js 16 + Bun, port 3050)
- **Security**: Citadel sidecar (Go, port 3001)
- **Database**: SQLite via SQLAlchemy async + ChromaDB for embeddings
- **AI**: Anthropic Sonnet 4.5 for agent reasoning

## Key Concepts

**Knowledge Capsules** — Typed units of knowledge (memory, skill, procedure, schedule, preference, contact) stored in encrypted vaults.

**Trust Tiers** — Three levels of access: public (anyone), network (shared group members), private (owner only).

**Networks** — User-created groups (family, team, friends) that define trust boundaries. Membership is explicitly managed.

**Connections** — Bidirectional relationships requiring manual approval. Prerequisite for network membership.

**Trust Resolution** — Algorithm that determines what capsules a requester can access based on connections and shared networks.

**Citadel** — Security sidecar that scans query inputs for prompt injection and outputs for data exfiltration.

**UCAN** — User Controlled Authorization Networks. Delegation-safe capability tokens where permissions can only shrink, never grow. Powers network membership, temporary access, and sub-delegation.
