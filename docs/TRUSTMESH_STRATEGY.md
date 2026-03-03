# TrustMesh Strategy

**Last Updated: February 18, 2026**

---

## The Core Thesis

**The model is fungible. The trust network is precious.**

AI assistants — Claude, GPT, Llama, and whatever comes next — will power most people's work and personal lives within a few years. Models will come and go. You will upgrade them, switch providers, or run local models depending on cost, capability, and privacy requirements. But your data, your relationships, and your trust network should persist across all of them.

TrustMesh is the persistent trust and data layer underneath any AI agent. Think of it like iCloud for your agent — except it is private by default, built on open standards, and works bidirectionally between trusted parties (not just your own devices).

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [The Analogy That Makes It Click](#2-the-analogy-that-makes-it-click)
3. [Why Current Protocols Fall Short](#3-why-current-protocols-fall-short)
4. [Where TrustMesh Sits in the Stack](#4-where-trustmesh-sits-in-the-stack)
5. [What TrustMesh Actually Does](#5-what-trustmesh-actually-does)
6. [PodOS Timeline: Beyond Cron](#6-podos-timeline-beyond-cron)
7. [Integration with nullclaw and OpenClaw](#7-integration-with-nullclaw-and-openclaw)
8. [The Model-Agnostic Bet](#8-the-model-agnostic-bet)
9. [The TEE Play: Provably Private](#9-the-tee-play-provably-private)
10. [agents.trymighty.ai: The Registry Play](#10-agentstrymightyai-the-registry-play)
11. [Live Demo Scenarios](#11-live-demo-scenarios)
12. [Competitive Position](#12-competitive-position)
13. [Market Validation](#13-market-validation)
14. [How We Win](#14-how-we-win)
15. [The One-Line Pitch](#15-the-one-line-pitch)

---

## 1. The Problem

Today, if your AI assistant talks to your sister's AI assistant, there is no secure way to control what they share.

There is no concept of "this is personal, don't share" versus "this is family-visible." There is no audit trail of what information crossed between agents. There is no way to revoke access after the fact. There is no encrypted storage on either end. And the model running the agent can see everything passed to it.

This is not a small gap. It is the entire trust infrastructure for the agent internet — and it does not exist yet.

### What people try today

- **Monitoring tools** (Zenity, Obsidian): Watch what agents do after the fact. The data has already moved.
- **Enterprise DLP** (Proofpoint, Acuvity): Pattern-matching filters, brittle, enterprise-only, bolted on after the fact.
- **Framework guardrails** (LangChain system prompts, CrewAI role constraints): Convention-based. Easily bypassed via prompt injection or model confusion.

None of these solve the actual problem: **private by default, share by intent, audited always.**

That is the gap TrustMesh fills.

---

## 2. The Analogy That Makes It Click

Apple solved device-to-device sharing elegantly across a range of scenarios:

- **AirDrop**: Nearby, one-time, user-approved, encrypted, no account needed.
- **Handoff**: Persistent, identity-bound (Apple ID), seamless continuity between devices.
- **iMessage**: Persistent channel, end-to-end encrypted, between people — not just devices.
- **Family Sharing**: Pool-like, but coarse — all-or-nothing access.

These are excellent for their purpose. But none of them work for AI agents. They are device-centric, not agent-centric. They are Apple-only, not open. They offer binary access (share or don't share), not tiered access (private, internal, or public).

**TrustMesh is the open, bidirectional, tiered, audited version of this for AI agents.**

When Alice's agent shares her mother's health update with her sister's agent:

- **Private capsules** (Alice's therapy notes): Never visible to the sister's agent. Not filtered out — they literally do not exist in the sister's agent's world.
- **Internal capsules** (family health updates): Visible through the Johnson Family trust pool.
- **Public capsules** (Alice's agent card, her agent's capabilities): Visible to anyone who asks.

This is not achieved by convention or configuration. It is enforced by architecture — cryptography at the storage layer, trust resolution at query time, and Citadel scanning at every egress point.

---

## 3. Why Current Protocols Fall Short

Academic research (arxiv 2511.03434) identifies six ways agents can establish trust with each other:

| Trust Model | Description | Example |
|-------------|-------------|---------|
| **Claim** | Self-description — I say who I am | Agent card: "I'm a certified financial planner" |
| **Brief** | Verifiable credential from a third party | Auditor attests: "This agent is HIPAA-compliant" |
| **Proof** | Cryptographic verification — math proves it | Ed25519 signature, ZK proof, TEE attestation |
| **Reputation** | Network-based signals — who vouches for you | Trust connections and pool membership |
| **Stake** | Economic collateral — skin in the game | Blockchain-style bonds |
| **Constraint** | Sandboxing — limit what the agent can do | Capability bounding, network isolation |

**Google's A2A protocol today: Claim + Constraint only.** An agent describes itself, and it runs in a sandbox. That is the entire trust model.

**TrustMesh today: Claim + Proof + Reputation + Constraint.**

- **Claim**: Agent card with a decentralized identifier (DID)
- **Proof**: Ed25519 cryptographic signatures, verifiable agent identity
- **Reputation**: Trust networks — connections you have made, pools you belong to, who vouches for you
- **Constraint**: Private, internal, and public data tiers enforced by cryptography, not by configuration files

The gap in every competing solution is Proof and Reputation. TrustMesh has both, today.

---

## 4. Where TrustMesh Sits in the Stack

```
┌─────────────────────────────────────────────────────────────────┐
│  Your life: work, health, family, finance, calendar             │
├─────────────────────────────────────────────────────────────────┤
│  Agent Runtimes  (what agents DO)                               │
│  nullclaw (Zig) · OpenClaw (TS) · CrewAI · LangGraph            │
│  Microsoft Agent Framework · OpenAI Agents SDK                  │
├─────────────────────────────────────────────────────────────────┤
│  ★★★  TRUSTMESH  ★★★                                            │
│  Private vault · Trust tiers · Gossip engine                   │
│  Federated pools · Audit trail · DIDs · PodOS Timeline          │
├──────────────────────┬──────────────────────────────────────────┤
│  Mighty Citadel      │  Communication Standards                 │
│  Multimodal scanning │  A2A Protocol (Linux Foundation)         │
│  Prompt injection    │  MCP (Anthropic → Linux Foundation)      │
│  TEE enforcement     │  DIDComm v2, W3C Verifiable Credentials  │
├──────────────────────┴──────────────────────────────────────────┤
│  Infrastructure (cloud, on-prem, edge, Raspberry Pi)            │
└─────────────────────────────────────────────────────────────────┘
```

TrustMesh sits **above** the communication standards and **below** the runtimes. It does not compete with any agent framework. It makes all of them compliant, trustworthy, and interoperable — without requiring any framework to change how it works.

---

## 5. What TrustMesh Actually Does

### The Pod

Every user or organization runs a TrustMesh pod. A pod is a self-contained unit:

- **Encrypted vault**: Capsules (knowledge units) stored with AES-256-GCM encryption. Keys never leave the pod's Zig transit engine — not even the server operator can read them.
- **Agent identity**: Ed25519 keypair, DID, agent card. Cryptographically verifiable — no "just trust me."
- **Trust graph**: Connections to other pods, membership in trust pools, resolution rules.
- **Audit log**: Immutable record of every cross-boundary data access.

Pods are batteries-included. SQLite embedded, FTS5 search (no ChromaDB, no external service), one-command start. They run on a Raspberry Pi or a cloud VM with equal ease.

### The Three Trust Tiers

Every capsule (piece of data) lives at exactly one trust tier:

- **Private**: Only the pod owner's agent sees this. Encrypted with the owner's vault key. Not queryable by anyone else.
- **Internal**: Visible to connected pods and pool members. Encrypted with the vault key, decrypted at query time only after trust resolution confirms the requester qualifies.
- **Public (Open)**: Visible to any agent that asks. The pod's "public face."

Trust is resolved at query time, not at storage time. When a remote agent queries your pod, the gossip engine evaluates the requester's trust level — based on your connection to them and shared pool membership — and returns only the capsules they are allowed to see. There is no "filter the bad stuff out" step. The inaccessible capsules do not exist from the requester's perspective.

### The Gossip Engine

The query path for every cross-pod request:

1. Requester's identity verified (DID + Ed25519 signature)
2. Trust level resolved: private, network (internal), or public
3. Citadel scans the query for injection or exfiltration patterns
4. Trust-scoped capsules retrieved (only what this requester's level permits)
5. Semantic search within that scoped set
6. Claude Sonnet 4.5 synthesizes a response from the allowed knowledge
7. Citadel scans the output before it leaves the pod
8. Audit log records the entire transaction

No step is optional. No framework convention replaces the cryptographic enforcement.

### Federated Pools

A pool is a shared trust agreement between multiple pods. Examples:

- Johnson Family Pool: Alice, her sister, their mother, their doctor — each with a pod
- Riverside Hospital Pool: Hospital + affiliated physicians + emergency contacts
- TechCorp PM Team: Employees + contractors + a partner organization

Pool membership grants "internal" trust between members. A capsule marked internal is visible to all pool members. The pool has a shared encryption context. Membership is managed cryptographically, with one-time invite tokens and a global ghost cap to prevent abuse.

Pools are federated — they span independently-operated pods. No central server holds the keys or controls membership.

---

## 6. PodOS Timeline: Beyond Cron

Most agent frameworks have a scheduler. "Run this task every day at 9am." That is useful but limited.

TrustMesh ships the PodOS Timeline kernel — a Zig-native temporal execution engine that handles the class of workflows no cron scheduler can express.

### The Difference

**Cron**: Fire at time T → agent runs → done.

**PodOS Timeline**:

- Each entry has a full state machine: dormant → pending → activating → active → deactivating → completed (or failed or archived)
- DAG dependencies: entry B does not activate until entries A and C complete
- Three-stream data resolution: private, internal, and public data streams are evaluated separately; the losing streams are shadowed (salience reduced by 70%), not discarded
- Event-driven triggers: not just time — capsule updates, threshold crossings, external events
- Hook dispatch: a timeline entry activates → the Zig kernel fires a callback → the Python agent runtime picks it up → full trust context is passed to the agent task
- Cross-pod coordination: entries can span multiple pods within a pool

### A Real Example

"When Mom's blood pressure capsule is updated AND the reading exceeds the threshold AND Dr. Lee has not acknowledged the previous alert AND it is a weekday, share the updated readings with the Riverside Hospital pool AND create a pending timeline entry for Dr. Lee's agent to respond within four hours. If Dr. Lee's agent does not respond, escalate to the on-call nurse's agent."

No cron scheduler does this. No LangChain workflow does this with trust-aware data access at each step. PodOS Timeline + TrustMesh trust layer does this — with every data access audited and every output scanned by Citadel.

### The Bridge to Other Frameworks

OpenClaw reads your Google Calendar. The events become TrustMesh timeline entries. PodOS manages the trust-aware execution. Citadel scans the output. The right data reaches the right agents. The calendar integration stays in OpenClaw (it is already excellent). The trust and temporal orchestration move into TrustMesh.

---

## 7. Integration with nullclaw and OpenClaw

### What nullclaw Already Built (We Do Not Rebuild)

nullclaw is an excellent agent runtime: a single Zig binary under 1MB, sub-2ms startup, 22+ LLM providers, 13 communication channels (Telegram, Discord, Slack, WhatsApp, and others), cron scheduler, SQLite memory with embeddings, ChaCha20 encryption for agent secrets, sandbox backends, and a daemon supervisor.

Critically, nullclaw is built around vtable interfaces: memory, tools, providers, channels, and tunnels are all pluggable.

### What OpenClaw Already Built (We Do Not Rebuild)

OpenClaw brought lane queue architecture (serial by default, parallel for low-risk tasks), robust session management, and multimodal multi-agent capability. Its 190K GitHub stars reflect a large developer community, and its tool integrations for calendar, email, and messaging are mature.

### What TrustMesh Adds That Neither Has

- Encrypted personal vault (your data, your keys — not the runtime's)
- Trust tiers enforced by cryptography (not system prompt conventions)
- Cross-pod agent-to-agent secure sharing via the gossip engine
- Federated pools for cross-organization collaboration with defined trust boundaries
- Tamper-evident audit trail of every trust-boundary crossing
- Verifiable agent identity (DIDs, Ed25519 signatures)
- PodOS Timeline kernel for trust-aware temporal orchestration
- Mighty Citadel protection at every egress point

### The Integration Points

**nullclaw memory vtable → TrustMesh capsule store:**

```
Before: nullclaw search query → vector search → unfiltered results
After:  nullclaw search query → TrustMesh trust resolution → scoped capsule results
```

The agent gets back only what its trust level permits. The underlying vector search happens within the already-scoped set.

**nullclaw tools → add TrustMesh tools:**

```
query_vault(topic, trust_scope)
share_capsule(capsule_id, target_pod)
verify_agent(did)  → trust_level
audit_action(what, evidence)
```

**nullclaw cron → TrustMesh timeline:**

```
cron trigger → timeline entry created → PodOS state machine activates →
trust-scoped data query → Citadel scan → output delivered to authorized pods
```

**The division of responsibility is clean:**

nullclaw handles "what do I do and when" — integrations, channels, LLM routing. TrustMesh handles "who can see what" — vault, trust resolution, audit. PodOS Timeline handles "complex conditional workflows across trust boundaries." Citadel handles "is this safe to send."

No framework needs to change its architecture. TrustMesh plugs into what already works.

---

## 8. The Model-Agnostic Bet

This is the architectural decision that makes TrustMesh defensible over time.

Today, developers build "Claude-based assistants" or "GPT-based assistants" as though the model is the agent. It is not. The model is the reasoning engine. Models are fungible.

GPT-3.5 → GPT-4 → GPT-4o → GPT-5. Claude 2 → 3 → 3.5 → Sonnet 4.5. Local models (Llama 4) for privacy-sensitive tasks. Cloud models for complex reasoning. TEE models for compliance requirements. The model you use will change, possibly frequently.

**What does not change**: Your data, your relationships, your history, your trust network.

TrustMesh is the persistent identity layer — the part of the agent that survives model upgrades:

- **Vault**: Your encrypted personal knowledge base, independent of any model provider
- **Trust network**: Your connections, your pool memberships, the relationships you have built
- **Timeline**: What happened — an immutable, audited record of agent actions and decisions
- **DID + Ed25519**: Your verifiable cryptographic identity

Switch from Claude to Llama to Gemini: your TrustMesh pod follows you. The model is just the engine you rent. The pod is what you own.

This is not a theoretical position. It is reflected in the architecture: the gossip engine passes trust-scoped data to whatever model is configured. The model sees only what its user's trust tier permits — regardless of which model it is.

---

## 9. The TEE Play: Provably Private

Today's privacy claims are assertions: "trust us, we encrypt it."

TEE-based privacy is a proof: "even we cannot see it — here is the hardware attestation receipt."

Trusted Execution Environments (Intel SGX, AMD SEV, ARM TrustZone) provide hardware-enforced isolation. Even the cloud operator running the server cannot inspect what executes inside the enclave. The code running inside can produce a cryptographic attestation proving that it is exactly the code that was expected — and that it has not been tampered with.

**TrustMesh + TEE:**

- Vault keys never touch unprotected memory — the Zig transit engine holds them inside the enclave boundary
- Agent inference happens inside the enclave — the model physically cannot exfiltrate data outside the trust boundary
- Citadel scanning happens inside the TEE — the protection layer itself is provably untampered
- Audit logs are signed inside the TEE — tamper-evident with a hardware root of trust

This is what "private by default" means at the hardware level. Not a marketing claim. A cryptographic proof with a hardware-signed receipt.

The TEE play is particularly important for regulated industries. Healthcare, finance, and legal all need provable privacy — not contractual privacy. A HIPAA BAA says "we promise." TEE attestation says "here is the math."

---

## 10. agents.trymighty.ai: The Registry Play

Deploy the public agent registry at agents.trymighty.ai. This serves three purposes simultaneously.

### 1. Trust Anchor for the Agent Internet

Any agent registered here has a verified DID and optionally carries compliance verifiable credentials. When an agent in the wild connects to a pod registered at agents.trymighty.ai, it knows the agent is real — the DID is verified against the registry, and the Ed25519 signature proves the connecting agent actually controls that DID.

This is the "certificate authority" play for the agent internet. Not a gatekeeper — registration is open. But a trusted verification point that raises the cost of impersonation.

### 2. Live Demonstration Platform

The registry is also the best live demonstration of TrustMesh's value:

- Search agents by capability, entity type, or trust tier
- Click any agent → see its agent card, its capabilities, what it shares publicly
- Run the sister scenario: two live demo pods, connected through a family pool, watch what crosses trust boundaries and what stays private
- See a Citadel scan happen in real time as a cross-pod query is processed

This converts an abstract technical concept ("trust-tiered knowledge sharing") into something anyone can see in thirty seconds.

### 3. Mighty Citadel Commercial Hook

Agents registered on the registry can display a "Citadel-protected" badge. This badge means the agent's data egress is scanned by multimodal AI before leaving the pod — checking for prompt injection, exfiltration attempts, and information boundary violations.

No other agent registry offers this. It is a meaningful trust signal for anyone connecting to that agent. An enterprise evaluating whether to connect its internal agents to an external partner's agent has a concrete data point: does the partner's pod carry the Citadel badge?

This creates a natural commercial entry point for Mighty — and gives the registry a differentiator that grows in value as the agent ecosystem expands.

---

## 11. Live Demo Scenarios

These scenarios are all running today, not hypothetical.

### The Family Network

Dr. Lee (pod on port 8005) + Molly Johnson (pod 8001) + Riverside Hospital (pod 8012). A cross-pod query runs through three pods. Dr. Lee sees health data. Molly sees family updates. The hospital sees only what qualifies as open trust. Citadel scan results appear in the audit log. Run it live with `./multi-pod.sh demo`.

### The Calendar Handoff

OpenClaw reads a Google Calendar. Creates TrustMesh timeline entries for each event. PodOS manages trust-aware execution — each step in the event workflow runs with the correct trust scope. The right information reaches the right agents. The bridge between an existing framework and TrustMesh's trust layer, demonstrated end to end.

### The Cross-Framework Query

A nullclaw agent — a Zig binary under 1MB — calls the TrustMesh MCP server. Gets back trust-scoped capsule results based on its verified identity and trust level. The audit log records the query. Framework-agnostic trust enforcement running against an agent runtime that has no native trust model of its own.

### The TEE Attestation

Submit a message to a Citadel-protected pod. Receive a signed attestation receipt showing the scan occurred inside the TEE enclave. The receipt includes the code hash, the scan result, and the hardware signature. Provably private, provably scanned — not a policy, a proof.

### The Medical Alert Chain

A blood pressure capsule updates with a reading above threshold. PodOS Timeline evaluates the entry's DAG dependencies and activation conditions. The state machine fires. The agent queries the health pool with internal trust scope — getting readings Dr. Lee's agent would not get at public trust. Citadel scans the output. Dr. Lee's agent receives the notification. The audit trail shows every step: what data was accessed, what trust level authorized it, what Citadel found, and when delivery was confirmed.

---

## 12. Competitive Position

| Competitor | What They Do | Why TrustMesh Wins |
|------------|--------------|-------------------|
| **Zenity** | Monitors agent actions after they happen | TrustMesh controls what agents can access before they run — not watching, preventing |
| **Obsidian Security** | SaaS visibility into Salesforce and Microsoft Copilot | TrustMesh is infrastructure any framework uses, not a monitoring layer on top of one vendor |
| **Proofpoint / Acuvity** | Enterprise DLP bolted onto existing workflows | TrustMesh is compliance-native from day one, not retrofitted |
| **CrewAI / LangGraph / OpenClaw** | Agent runtimes — they handle what agents do and how | TrustMesh is the trust layer — who can see what, enforced by cryptography |
| **nullclaw** | Excellent at running everywhere with minimal resources | TrustMesh is the secure data and trust layer nullclaw is designed to integrate with |
| **Apple AirDrop / Handoff** | Device-centric, Apple-only, binary access control | TrustMesh is open, agent-centric, tiered, and bidirectional |
| **Google A2A** | Claim + Constraint trust only — agents describe themselves | TrustMesh adds Proof + Reputation — cryptographic identity, verifiable trust networks |

The white space is clear: nobody owns the trust layer for the open agent internet. Every runtime assumes trust is handled elsewhere. Every monitoring tool assumes it will watch traffic after it has already moved. TrustMesh is the layer that enforces trust before data moves — and proves it happened correctly after.

---

## 13. Market Validation

The market is paying for agent governance. The infrastructure does not exist yet.

- AI agent market: $7.84B in 2025, projected $52.6B by 2030 — 46% compound annual growth
- 40% of enterprise applications will embed agents by 2026 (Gartner), up from under 5% in 2025
- 35% of enterprises already use agents for business-critical workflows today
- Non-human identities (service accounts, bots, agents) outnumber human identities 40:1 to 100:1 in enterprises — the trust problem is not future, it is present
- Proofpoint acquired Acuvity in February 2026 — the market is actively paying for agent governance solutions
- Zenity named a Gartner Cool Vendor in Agentic AI TRiSM 2025
- Obsidian Security raised $40M+ — enterprise buyers have demonstrated willingness to spend on agent oversight

The acquisition of Acuvity and the Gartner recognition of Zenity confirm that enterprise buyers see agent governance as a purchasing priority. None of the funded players own the infrastructure layer. They all operate above it.

---

## 14. How We Win

### Now (Next 90 Days)

1. **Ship TrustMesh as an MCP server.** Any OpenClaw, nullclaw, CrewAI, or LangGraph agent can add trust-scoped capsule access in under five minutes. Zero framework changes required.

2. **Launch agents.trymighty.ai** with the family demo and the Citadel badge. Give developers a live sandbox to explore trust-tiered agent interaction. Give enterprise evaluators a concrete trust signal to point to.

3. **Write the definitive article**: "The Missing Trust Layer" — why every current agent protocol is Claim-only, what Proof and Reputation add, and why the industry will need both before agents touch regulated data. Publish in a venue developers read.

4. **Ship the nullclaw vtable plugin.** Memory integration and trust tools, packaged as a standard nullclaw extension. One-command install.

### Medium Term (6-12 Months)

1. **HIPAA BAA + SOC2 certification.** Healthcare and finance cannot use what they cannot audit. TrustMesh's architecture was built for this — pursue certification aggressively to own regulated verticals.

2. **`crewai-trustmesh` package.** CrewAI has the largest developer community among orchestration frameworks. A one-line integration that adds trust-scoped vault access to any CrewAI agent is the fastest path to broad adoption.

3. **Linux Foundation AAIF participation.** The Agent Authenticity and Identity Framework working group is where the open standards for agent trust will be written. TrustMesh should be a participant and, where possible, a contributor to the federated pool specification.

### Long Term (2-3 Years)

1. **TrustMesh becomes the trust anchor for the open agent internet.** Any agent that needs to share data across organizational boundaries either runs TrustMesh or integrates with it. The protocol, not the product, becomes the standard.

2. **agents.trymighty.ai becomes the authoritative public registry.** When enterprises need to verify an external agent's identity and compliance posture, they check the registry. The Citadel badge becomes a meaningful signal in procurement conversations.

3. **Mighty Citadel + TrustMesh becomes the security stack that compliance teams mandate.** In the same way that enterprises mandate SOC2 for SaaS vendors, they will mandate provable agent governance for AI-enabled integrations. TrustMesh is that standard.

### The Moat

The trust network is the moat. Once your pod is connected to your doctor's pod, your employer's pool, and your family network, that graph has real value. The connections are yours — you can export your data and relationships. But the history, the audit trail, and the cryptographic proof of every interaction live in the pod. Switching costs are real but fair: we do not lock you in by holding your data hostage, we earn the retention by being the infrastructure that everything else depends on.

---

## 15. The One-Line Pitch

**Your agent, your data, your rules — TrustMesh makes AI agents share securely between people, organizations, and frameworks, with private-by-default, audit-always trust that works like iCloud but open and bidirectional.**

---

*TrustMesh is built by Mighty. For questions about this document, contact the core team.*
