# Protocol Landscape: A2A, MCP, and Agent Communication

## Overview

The AI agent ecosystem is converging around three complementary protocol layers. TrustMesh sits at the intersection, providing the **trust layer** that none of these protocols address natively.

```
                          TrustMesh's Position
                                  |
    ┌─────────────────────────────┼─────────────────────────────┐
    │                             │                             │
    ▼                             ▼                             ▼
 Agent-to-Agent              Trust & Permissions          Agent-to-Tool
 (Google A2A)           (TrustMesh's contribution)       (Anthropic MCP)
 - Discovery              - Trust tiers                  - Tool execution
 - Task lifecycle          - Network gating               - Resource access
 - Agent cards             - Encrypted vaults             - OAuth 2.1 scopes
 - SSE streaming           - Citadel security             - JSON-RPC 2.0
```

---

## 1. Google A2A (Agent-to-Agent Protocol)

### What It Is

A2A is Google's open protocol enabling AI agents to discover, communicate with, and delegate tasks to each other. Announced in April 2025, it uses JSON-RPC 2.0 over HTTP and has been adopted by 100+ companies including Salesforce, SAP, Atlassian, and MongoDB.

### Core Concepts

#### Agent Cards

Every A2A agent publishes a discoverable JSON profile at `/.well-known/agent.json`:

```json
{
  "name": "Molly's Personal Agent",
  "description": "Molly Johnson's trust-aware knowledge agent",
  "url": "https://trustmesh.example.com/agents/molly",
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "authentication": {
    "schemes": ["Bearer"]
  },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain", "application/json"],
  "skills": [
    {
      "id": "knowledge-query",
      "name": "Knowledge Query",
      "description": "Query Molly's knowledge vault based on trust level",
      "tags": ["knowledge", "family", "work"],
      "examples": [
        "What medication does grandma take at night?",
        "When is the Q4 report due?"
      ]
    }
  ]
}
```

#### Task Lifecycle

A2A defines a strict task state machine:

```
submitted → working → completed
                   → failed
                   → canceled
```

Each task carries:
- **Message history**: Conversation turns between agents
- **Artifacts**: Structured outputs (files, data, etc.)
- **Metadata**: Trust context, timing, routing info

#### Communication Patterns

| Pattern | Mechanism | Use Case |
|---------|-----------|----------|
| Request-Response | HTTP POST to `/tasks` | Simple queries |
| Streaming | Server-Sent Events (SSE) | Real-time agent responses |
| Push Notifications | Webhook callbacks | Async task completion |

#### Authentication

A2A supports multiple auth schemes but **does not prescribe a trust model**:

- OAuth 2.0 (bearer tokens)
- API keys
- Mutual TLS (mTLS)
- Custom schemes (via Agent Card declaration)

### What A2A Lacks

| Gap | Impact | TrustMesh Fills It |
|-----|--------|-------------------|
| No trust tiers | All agents are either authenticated or not — no "family vs coworker" distinction | Trust-tiered gossip protocol |
| No E2E encryption | Messages in transit only (TLS), not at rest | AES-256-GCM encrypted vaults |
| No fine-grained access control | Binary allow/deny, no per-network capsule gating | Network-scoped capsule sharing |
| No knowledge management | Agents have no structured memory model | Knowledge capsules with types, tiers, freshness |
| No security scanning | No built-in protection against prompt injection or data exfiltration | Citadel input/output scanning |
| No audit trail | No standard for logging trust decisions | Query log with trust level, Citadel results, decision |

### How TrustMesh Uses A2A

We implement A2A-compatible agent cards so that external tools can discover our agents:

```
GET /api/users/{id}/agent/card → A2A Agent Card JSON

External A2A Client
    → discovers TrustMesh agent via /.well-known/agent.json
    → sends query via standard A2A task creation
    → TrustMesh applies trust resolution before responding
    → response follows A2A task lifecycle
```

The key insight: **A2A handles the transport, TrustMesh handles the trust**.

---

## 2. Anthropic MCP (Model Context Protocol)

### What It Is

MCP is Anthropic's client-server protocol that connects AI applications (Claude Desktop, Claude Code, Cursor) to external data and tools. It defines how an AI host discovers and uses capabilities from external servers.

### Architecture

```
MCP Host (Claude Code, Cursor, etc.)
├── MCP Client 1 ──► MCP Server 1 (filesystem)
├── MCP Client 2 ──► MCP Server 2 (database)
└── MCP Client 3 ──► MCP Server 3 (TrustMesh agent)
```

Key distinction: MCP is **vertical** (AI app → tools/data), while A2A is **horizontal** (agent → agent).

### Three Primitives

| Primitive | Control | Purpose | TrustMesh Mapping |
|-----------|---------|---------|-------------------|
| **Tools** | Model-controlled | Execute actions, modify state | `query_agent`, `add_capsule`, `manage_network` |
| **Resources** | App-controlled | Read-only data access | `vault://capsules`, `graph://trust-level` |
| **Prompts** | User-controlled | Workflow templates | `query-with-trust`, `share-knowledge` |

### Transport Mechanisms

| Transport | Use Case | Auth Model |
|-----------|----------|------------|
| STDIO | Local processes (same machine) | Environment variables |
| HTTP (Streamable) | Remote servers | OAuth 2.1 with PKCE |

### OAuth 2.1 Authorization

MCP's HTTP transport uses OAuth 2.1 with several innovations:

1. **Resource-Bound Tokens** (RFC 8707): Tokens are bound to their intended resource, preventing reuse across services
2. **PKCE** (Proof Key for Code Exchange): Prevents authorization code interception
3. **Client ID Metadata Documents**: Agents use HTTPS URLs as client IDs, solving the "zero pre-existing relationship" problem
4. **Scope-Based Authorization**: Fine-grained per-tool access control with step-up authorization

```
Authorization Flow:
1. Client makes unauthenticated request
2. Server responds 401 with WWW-Authenticate header
3. Client discovers Authorization Server metadata
4. Client performs Authorization Code Flow + PKCE
5. Server validates token audience + scopes
6. Client includes Bearer token in subsequent requests
```

### The Agent Gateway Pattern

For TrustMesh, MCP enables AI coding tools to query our agents:

```
Claude Code
    └── MCP Client
          └── HTTP + OAuth 2.1
                └── TrustMesh MCP Server
                      ├── Tool: query_agent(target_user, question)
                      ├── Tool: search_vault(query, scope)
                      ├── Resource: vault://my-capsules
                      ├── Resource: graph://my-networks
                      └── Prompt: "Query with trust context"
                            └── Trust Resolution → Sonnet 4.5 → Citadel → Response
```

### MCP Server Implementation (Future)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("trustmesh-agent")

@mcp.tool()
async def query_agent(target_username: str, question: str) -> str:
    """Query another user's agent through the TrustMesh trust layer."""
    # Auth: OAuth token identifies the requesting user
    # Trust: Resolve trust level between authenticated user and target
    # Execute: Full query pipeline (trust → citadel → retrieval → agent → citadel)
    result = await gossip.query_agent(from_user, to_user, question)
    return json.dumps(result)

@mcp.resource("vault://capsules")
async def list_my_capsules() -> str:
    """List the authenticated user's knowledge capsules."""
    capsules = await get_user_capsules(authenticated_user_id)
    return json.dumps([c.to_dict() for c in capsules])
```

### What MCP Lacks

| Gap | TrustMesh Fills It |
|-----|-------------------|
| No agent-to-agent communication (client-server only) | A2A layer handles peer queries |
| No built-in trust negotiation | Trust-tiered gossip protocol |
| No multi-hop authorization ("A authorizes B to access C") | Network-based delegation |
| No behavioral constraints on responses | Citadel output scanning |

---

## 3. AgentMail

### What It Is

AgentMail provides email-based identity and communication for AI agents. Each agent gets an email address (e.g., `mollys-agent@agentmail.to`) and communicates via standard IMAP/SMTP protocols.

### Core Concepts

- **Agent Identity**: Email address = unique agent identifier
- **Message Threading**: IMAP threads provide conversation history
- **REST + IMAP/SMTP**: Dual access (programmatic API + standard email protocols)
- **Persistent Memory**: Thread history serves as agent memory

### Comparison with A2A and MCP

| Feature | AgentMail | A2A | MCP |
|---------|-----------|-----|-----|
| Communication | Email (IMAP/SMTP) | HTTP + SSE | JSON-RPC over STDIO/HTTP |
| Discovery | Email address lookup | Agent Cards | Server configuration |
| Identity | Email address | URL + Agent Card | Client ID |
| Auth | API key | OAuth2/mTLS/API key | OAuth 2.1 |
| Real-time | No (polling) | Yes (SSE) | Yes (streaming) |
| Trust Model | None | None | Scope-based |
| Structured Data | Email body (text/HTML) | JSON artifacts | JSON-RPC responses |

### Assessment for TrustMesh

AgentMail is too limited for TrustMesh's needs:
- **No trust model**: No concept of networks, tiers, or access control
- **No encryption**: Email content is not E2E encrypted
- **No real-time**: Polling-based, high latency for interactive queries
- **No structured knowledge**: Messages are flat text, not typed capsules

**Verdict**: Build our own. TrustMesh's value is the trust layer — AgentMail doesn't help with that.

---

## 4. Emerging Standards

### AAIF (Linux Foundation)

The AI Agent Interoperability Forum is working to converge A2A + MCP + Agent Skills Protocol + AGENTS.md into a unified standard. Key work:

- **Agent Skills Protocol**: Standardized capability descriptions
- **AGENTS.md**: Convention file (like robots.txt for agents) describing what an agent can do
- **Unified Discovery**: Single mechanism to find both A2A agents and MCP servers

### FIPA ACL (Historical)

The Foundation for Intelligent Physical Agents defined Agent Communication Language in the early 2000s. While not directly used today, its concepts influence modern protocols:
- Performatives (inform, request, propose, refuse)
- Content language negotiation
- Conversation protocols (contract net, auction)

### DIDComm

W3C's Decentralized Identity Communication protocol uses DIDs (Decentralized Identifiers) for authenticated, encrypted agent messaging. Relevant concepts:
- **Self-sovereign identity**: Agents control their own keys
- **Verifiable Credentials**: Cryptographic proof of claims
- **Message routing**: Privacy-preserving relay networks

---

## 5. Protocol Comparison Matrix

| Dimension | A2A | MCP | AgentMail | TrustMesh |
|-----------|-----|-----|-----------|-----------|
| **Primary Use** | Agent-to-agent tasks | AI app-to-tool | Agent messaging | Trust-aware knowledge sharing |
| **Transport** | HTTP + SSE | STDIO / HTTP | IMAP/SMTP | HTTP (FastAPI) |
| **Message Format** | JSON-RPC 2.0 | JSON-RPC 2.0 | Email (MIME) | JSON REST |
| **Discovery** | Agent Cards | Manual config | Email lookup | User search + connection approval |
| **Auth** | OAuth2/mTLS/API key | OAuth 2.1 | API key | httpOnly session cookies |
| **Trust Model** | None (binary auth) | Scope-based | None | Three-tier (public/network/private) |
| **Encryption** | TLS only | TLS only | TLS only | AES-256-GCM at rest + TLS in transit |
| **Knowledge Model** | None | Resources (generic) | Email threads | Typed capsules with freshness |
| **Security Scanning** | None | None | None | Citadel (input + output) |
| **Network Concept** | None | None | None | User-created networks with manual membership |
| **Audit Trail** | None standard | None standard | None | Full query log with trust decisions |

---

## 6. Integration Strategy

### What We Build (Hackathon)

1. **A2A Agent Cards**: `/api/users/{id}/agent/card` endpoint returning A2A-compatible JSON
2. **Trust-Tiered Query Pipeline**: Our core protocol (trust → citadel → retrieval → agent → citadel)
3. **Encrypted Knowledge Vault**: AES-256-GCM capsules with tier-based access
4. **Citadel Security Layer**: Input/output scanning on all queries
5. **Query Audit Log**: Full trace of every trust decision

### What We Mention (Demo/Slides)

1. **MCP Server**: Future integration so Claude Code/Cursor can query TrustMesh agents
2. **A2A Task Lifecycle**: Our queries already follow submitted → working → completed
3. **Capability Tokens**: Biscuit-style attenuable tokens for delegation
4. **AAIF Compatibility**: Our architecture aligns with the emerging unified standard

### What We Skip

1. Full A2A protocol implementation (we implement the card + compatible query flow)
2. MCP server (mention as future, don't build for hackathon)
3. AgentMail integration (not a good fit)
4. DIDComm/UCAN (production-grade, overkill for demo)
