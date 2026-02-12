# Agent Discovery: How Agents Find and Authenticate Each Other

## Overview

Agent discovery answers two questions:
1. **How do I find another agent?** (Discovery)
2. **How do I verify they are who they claim to be?** (Authentication)

TrustMesh takes an opinionated stance: **discovery is human-mediated, not automated**. This is a feature, not a limitation — it means trust is grounded in human relationships.

---

## 1. Discovery Approaches in the Ecosystem

### Comparison

| Approach | How It Works | Trust Model | TrustMesh Fit |
|----------|-------------|-------------|---------------|
| **Well-Known Endpoints** (A2A) | Agent Card at `/.well-known/agent.json` | None (transport-level auth) | Yes — we serve agent cards |
| **Central Registry** | Agents register with a directory service | Registry operator is trusted | No — we're not a registry |
| **DNS-Based (ANS)** | Agent Name System, like DNS for agents | DNS infrastructure trust | Future consideration |
| **DHT-Based** (AGNTCY) | Distributed hash table, P2P discovery | Cryptographic verification | Too complex for hackathon |
| **Gossip Protocol** | Agents tell peers about other agents | Emergent, reputation-based | Conceptually aligned |
| **Human-Mediated** (TrustMesh) | Users search, connect, create networks | Human judgment | Our core model |

### Why Human-Mediated Discovery

The key insight: **AI agents should inherit trust from human relationships, not negotiate it through protocol handshakes.**

```
Traditional Agent Discovery:
  Agent A broadcasts: "I exist and can do X"
  Agent B discovers A through DHT/registry/gossip
  A and B negotiate trust through credentials
  Problem: Who issued the credentials? How do you trust the issuer?

TrustMesh Discovery:
  Peter connects to Molly (his wife) — he knows her
  Peter creates "The Johnsons" network — he decides who's family
  Peter's agent inherits trust from Peter's relationships
  Problem solved: Trust comes from the humans, not the protocol
```

---

## 2. TrustMesh Discovery Flow

### User Discovery

```
1. Kyle wants to connect with Molly (his coworker)
2. Kyle searches: GET /api/users?search=molly
3. API returns discoverable users matching "molly"
   - Only users with is_discoverable=true appear
   - Returns: display_name, bio, username (NOT private data)
4. Kyle finds Molly's public profile
5. Kyle sends connection request with message:
   "Hi Molly, it's Kyle from TechCorp!"
```

### Agent Discovery (A2A Compatible)

```
External AI Tool wants to query Peter's agent:

1. Fetch Agent Card:
   GET /api/users/peter/agent/card

2. Response:
   {
     "name": "Peter's Agent",
     "description": "Peter Johnson's trust-aware knowledge agent",
     "url": "https://trustmesh.example.com/api/query",
     "capabilities": {
       "streaming": false,
       "trustLevels": ["public", "network", "private"]
     },
     "authentication": {
       "schemes": ["Bearer"],
       "note": "Trust level depends on authenticated user's relationship to Peter"
     },
     "skills": [
       {
         "id": "knowledge-query",
         "name": "Query Peter's Knowledge",
         "description": "Ask about Peter's public knowledge (electrician, home)"
       }
     ]
   }

3. External tool authenticates (OAuth 2.1 / API key)
4. Sends query through standard endpoint
5. TrustMesh applies trust resolution based on authenticated identity
```

---

## 3. Authentication Patterns

### Current: Session-Based

```
Browser → POST /api/auth/login {username, password}
       ← Set-Cookie: trustmesh_session=<token>; HttpOnly; SameSite=Lax

Browser → GET /api/auth/me (cookie sent automatically)
       ← {user_id, username, display_name}

Browser → POST /api/query (cookie sent automatically)
       ← Trust-resolved response
```

### Future: OAuth 2.1 for External Tools

For MCP/A2A integration, external tools would authenticate via OAuth 2.1:

```
Claude Code → Authorization Request (PKCE)
           → User approves in browser
           → Authorization Code returned
           → Exchange for access token (resource-bound)
           → Use Bearer token for API calls
           → Token scope determines maximum trust level
```

### Future: Agent-to-Agent Authentication

For direct agent-to-agent communication (not through the web UI):

```
Option A: Mutual TLS (mTLS)
  - Each agent has a TLS certificate
  - Certificates verified during handshake
  - Identity bound to certificate

Option B: Signed Requests
  - Each agent has a keypair
  - Requests include signature header
  - Receiving agent verifies signature against known public key

Option C: Capability Tokens
  - Tokens issued by TrustMesh authorization server
  - Include agent identity, scope, expiry
  - Verified locally without server roundtrip
```

---

## 4. Agent Cards (A2A Format)

### TrustMesh Agent Card Schema

```json
{
  "name": "Molly's Agent",
  "description": "Molly Johnson's trust-aware personal AI agent. Senior PM at TechCorp, mother of two, caretaker for Grandma Rose.",
  "url": "https://trustmesh.example.com/api/agents/molly",
  "provider": {
    "organization": "TrustMesh",
    "url": "https://trustmesh.example.com"
  },
  "version": "1.0.0",
  "documentationUrl": "https://trustmesh.example.com/docs",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false,
    "trustAware": true,
    "encryptedVault": true,
    "citadelProtected": true
  },
  "authentication": {
    "schemes": ["Bearer"],
    "trustLevels": ["public", "network", "private"],
    "note": "Response content depends on authenticated user's trust level with Molly"
  },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain", "application/json"],
  "skills": [
    {
      "id": "knowledge-query",
      "name": "Knowledge Query",
      "description": "Query Molly's knowledge based on your trust level. Public queries return general information. Network members can access shared knowledge capsules.",
      "tags": ["knowledge", "family", "work", "health"],
      "examples": [
        "When is the Q4 report due?",
        "What is Molly's professional background?"
      ]
    }
  ],
  "securityPolicy": {
    "inputScanning": "citadel-heuristic",
    "outputScanning": "citadel-heuristic",
    "encryptionAtRest": "AES-256-GCM",
    "auditLogging": true
  }
}
```

### How Agent Cards Enable Interoperability

```
1. External A2A client fetches agent card
2. Card describes capabilities, auth requirements, and trust model
3. Client authenticates (getting a Bearer token)
4. Client sends queries via standard HTTP POST
5. TrustMesh resolves trust based on the authenticated identity
6. Response follows standard A2A format
7. Client doesn't need to understand TrustMesh internals —
   it just sees "I got an answer" or "I was denied"
```

---

## 5. Gossip Protocol for Trust Propagation (Conceptual)

While TrustMesh uses human-mediated connections, the trust-tiered gossip concept is central:

### How Trust Propagates

```
Peter creates "The Johnsons" network
    → Peter, Molly, Jane, Bill are members
    → Any member's agent can query other members' agents
    → Trust flows through the network membership, not direct connections

Molly creates "TechCorp PM Team" network
    → Molly, Kyle are members
    → Kyle can query Molly's agent for work-related capsules
    → Kyle CANNOT see family capsules (different network)

Trust is NOT transitive by default:
    → Kyle is connected to Molly
    → Molly is connected to Peter
    → Kyle is NOT automatically trusted by Peter's agent
    → Kyle must separately connect to Peter AND share a network
```

### Trust Graph Structure

```
Nodes: Users (each with an agent)
Edges: Accepted connections (bidirectional)
Clusters: Networks (colored groups)
Trust Level: Determined by edge (connected?) + cluster (shared network?)

    Peter ──────── Molly ──────── Kyle
      │    [family]   │   [work]
      │               │
    Jane ──────── Bill
         [family]

Network: "The Johnsons" = {Peter, Molly, Jane, Bill}
Network: "TechCorp PM" = {Molly, Kyle}

Trust from Kyle → Peter: PUBLIC (no connection)
Trust from Kyle → Molly: NETWORK (connected + shared "TechCorp PM")
Trust from Bill → Jane:  NETWORK (connected + shared "The Johnsons")
Trust from Bill → Kyle:  PUBLIC (no connection)
```

---

## 6. Future: Decentralized Identity (DIDs)

For a production TrustMesh, Decentralized Identifiers could replace server-managed accounts:

```
Current (Hackathon):
  Identity = server-managed user account (username + password)
  Trust = server-managed connections and networks
  Keys = server-managed vault keys

Future (DID-based):
  Identity = did:web:trustmesh.example.com:users:molly
  Trust = Verifiable Credentials (signed by network owners)
  Keys = User-controlled keypairs (WebAuthn PRF or hardware keys)

Benefits:
  - User owns their identity (not the server)
  - Credentials portable across TrustMesh instances
  - Offline verification of trust claims
  - Revocation via DID document updates
```

### Verifiable Credentials for Trust

```json
{
  "@context": ["https://www.w3.org/2018/credentials/v1"],
  "type": ["VerifiableCredential", "NetworkMembership"],
  "issuer": "did:web:trustmesh.example.com:users:peter",
  "credentialSubject": {
    "id": "did:web:trustmesh.example.com:users:bill",
    "memberOf": {
      "network": "The Johnsons",
      "networkType": "family",
      "role": "member",
      "since": "2025-01-15"
    }
  },
  "proof": {
    "type": "Ed25519Signature2020",
    "verificationMethod": "did:web:trustmesh.example.com:users:peter#key-1"
  }
}
```

This credential proves: "Peter (the network owner) attests that Bill is a member of The Johnsons." Any agent can verify this without contacting the TrustMesh server.
