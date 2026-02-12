# API Reference

## Base URL

```
Development: http://localhost:8000
```

## Authentication

All authenticated endpoints use httpOnly session cookies. The cookie is set automatically on login/signup and sent with every request.

```
Cookie: trustmesh_session=<token>
```

---

## Auth Endpoints

### POST /api/users
Create a new user account (signup). Sets session cookie automatically.

**Request Body:**
```json
{
  "username": "peter",
  "display_name": "Peter Johnson",
  "bio": "Licensed electrician, dad of two.",
  "password": "TrustMesh-demo-2026"
}
```

**Password Requirements:**
- 16-128 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character

**Response (200):**
```json
{
  "id": "uuid",
  "username": "peter",
  "display_name": "Peter Johnson",
  "bio": "Licensed electrician, dad of two.",
  "is_discoverable": true,
  "created_at": "2025-02-12T00:00:00Z"
}
```

**Errors:**
- `400` — Username already taken
- `422` — Validation error (weak password, missing fields)

**Notes:**
- Creates the user, their personal agent, and an empty vault
- Session cookie is set in the response (httpOnly)
- No token appears in the response body (security by design)

---

### POST /api/auth/login
Log in with username and password.

**Request Body:**
```json
{
  "username": "peter",
  "password": "TrustMesh-demo-2026"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "username": "peter",
  "display_name": "Peter Johnson"
}
```

**Errors:**
- `401` — Invalid credentials
- `429` — Too many login attempts (rate limited)

---

### GET /api/auth/me
Get the currently authenticated user.

**Response (200):**
```json
{
  "id": "uuid",
  "username": "peter",
  "display_name": "Peter Johnson",
  "bio": "Licensed electrician, dad of two.",
  "is_discoverable": true
}
```

**Errors:**
- `401` — Not authenticated (no valid session)

---

### POST /api/auth/logout
Log out and invalidate the current session.

**Response (200):**
```json
{
  "status": "ok"
}
```

---

## User Endpoints

### GET /api/users
List discoverable users. Supports search.

**Query Parameters:**
- `search` (optional) — Filter by username or display name

**Response (200):**
```json
[
  {
    "id": "uuid",
    "username": "peter",
    "display_name": "Peter Johnson",
    "bio": "Licensed electrician, dad of two.",
    "is_discoverable": true
  }
]
```

---

### GET /api/users/{id}
Get a user's public profile.

**Response (200):**
```json
{
  "id": "uuid",
  "username": "peter",
  "display_name": "Peter Johnson",
  "bio": "Licensed electrician, dad of two.",
  "is_discoverable": true
}
```

---

### GET /api/users/{id}/agent
Get a user's agent details.

**Response (200):**
```json
{
  "id": "uuid",
  "owner_id": "uuid",
  "name": "Peter's Agent",
  "personality": "Helpful, protective, knowledgeable about electrical work"
}
```

---

### GET /api/users/{id}/agent/card
Get A2A-compatible agent card.

**Response (200):**
```json
{
  "name": "Peter's Agent",
  "description": "Peter Johnson's trust-aware personal AI agent",
  "url": "/api/query",
  "capabilities": {
    "streaming": false,
    "trustAware": true,
    "citadelProtected": true
  },
  "authentication": {
    "schemes": ["Bearer"],
    "trustLevels": ["public", "network", "private"]
  },
  "skills": [
    {
      "id": "knowledge-query",
      "name": "Knowledge Query",
      "description": "Query Peter's knowledge based on trust level"
    }
  ]
}
```

---

## Connection Endpoints

### POST /api/connections/request
Send a connection request to another user.

**Request Body:**
```json
{
  "from_user_id": "uuid",
  "to_user_id": "uuid",
  "message": "Hi Peter, it's Kyle from Molly's work!"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "status": "pending",
  "created_at": "2025-02-12T00:00:00Z"
}
```

---

### GET /api/users/{id}/connections
List a user's accepted connections.

**Response (200):**
```json
[
  {
    "id": "uuid",
    "from_user_id": "uuid",
    "to_user_id": "uuid",
    "status": "accepted",
    "created_at": "2025-02-12T00:00:00Z",
    "accepted_at": "2025-02-12T01:00:00Z"
  }
]
```

---

### GET /api/users/{id}/connection-requests
List pending connection requests for a user.

**Response (200):**
```json
[
  {
    "id": "uuid",
    "from_user_id": "uuid",
    "to_user_id": "uuid",
    "message": "Hi Peter, it's Kyle!",
    "status": "pending",
    "created_at": "2025-02-12T00:00:00Z"
  }
]
```

---

### PUT /api/connection-requests/{id}
Accept or decline a connection request.

**Request Body:**
```json
{
  "status": "accepted"
}
```
or
```json
{
  "status": "declined"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "status": "accepted",
  "accepted_at": "2025-02-12T01:00:00Z"
}
```

---

## Network Endpoints

### POST /api/networks
Create a new network.

**Request Body:**
```json
{
  "name": "The Johnsons",
  "description": "The Johnson family",
  "network_type": "family",
  "owner_id": "uuid"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "name": "The Johnsons",
  "network_type": "family",
  "owner_id": "uuid",
  "created_at": "2025-02-12T00:00:00Z"
}
```

---

### GET /api/users/{id}/networks
List networks a user belongs to.

**Response (200):**
```json
[
  {
    "id": "uuid",
    "name": "The Johnsons",
    "network_type": "family",
    "owner_id": "uuid",
    "member_count": 4
  }
]
```

---

### GET /api/networks/{id}
Get network details including members.

**Response (200):**
```json
{
  "id": "uuid",
  "name": "The Johnsons",
  "network_type": "family",
  "owner_id": "uuid",
  "members": [
    {"user_id": "uuid", "username": "peter", "role": "owner"},
    {"user_id": "uuid", "username": "molly", "role": "member"},
    {"user_id": "uuid", "username": "jane", "role": "member"},
    {"user_id": "uuid", "username": "bill", "role": "member"}
  ]
}
```

---

### POST /api/networks/{id}/members
Add a connected user to a network.

**Request Body:**
```json
{
  "user_id": "uuid"
}
```

---

### DELETE /api/networks/{id}/members/{user_id}
Remove a user from a network.

---

## Knowledge Capsule Endpoints

### POST /api/users/{id}/capsules
Add a knowledge capsule to a user's vault.

**Request Body:**
```json
{
  "capsule_type": "procedure",
  "title": "Grandma Rose's Care Routine",
  "content": "MORNING: 7am wake up...",
  "tier": "network",
  "network_ids": ["uuid"],
  "category": "health",
  "freshness": "permanent"
}
```

**Capsule Types:** `memory`, `skill`, `procedure`, `schedule`, `preference`, `contact`
**Tiers:** `public`, `network`, `private`
**Freshness:** `permanent`, `temporary`, `recurring`

---

### GET /api/users/{id}/capsules
List a user's capsules (owner view — all tiers).

**Response (200):**
```json
[
  {
    "id": "uuid",
    "capsule_type": "procedure",
    "title": "Grandma Rose's Care Routine",
    "tier": "network",
    "category": "health",
    "freshness": "permanent",
    "is_archived": false,
    "created_at": "2025-02-12T00:00:00Z",
    "updated_at": "2025-02-12T00:00:00Z"
  }
]
```

---

### PUT /api/capsules/{id}
Update a capsule's content, tier, or network assignment.

---

### DELETE /api/capsules/{id}
Delete a capsule from the vault.

---

## Query Endpoints (The Core)

### POST /api/query
Query another user's agent through the trust layer.

**Request Body:**
```json
{
  "from_user_id": "uuid",
  "to_user_id": "uuid",
  "question": "What medication does grandma take at night?"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "decision": "allowed",
  "response": "For Grandma Rose's evening routine: At 7pm she takes Lisinopril 10mg and Amlodipine 5mg...",
  "trust_level": "network",
  "shared_networks": ["The Johnsons"],
  "citadel_input_score": 0.03,
  "citadel_input_decision": "ALLOW",
  "citadel_output_safe": true,
  "citadel_output_findings": [],
  "latency_ms": 1847,
  "created_at": "2025-02-12T00:00:00Z"
}
```

**Decision Values:**
- `allowed` — Query processed, response returned
- `denied` — Citadel blocked the input (prompt injection)
- `redacted` — Citadel flagged the output (data exfiltration)

---

### GET /api/users/{id}/queries
Get query history (sent and received).

**Response (200):**
```json
[
  {
    "id": "uuid",
    "from_user_id": "uuid",
    "to_user_id": "uuid",
    "question": "What medication does grandma take at night?",
    "trust_level": "network",
    "decision": "allowed",
    "latency_ms": 1847,
    "created_at": "2025-02-12T00:00:00Z"
  }
]
```

---

## Graph Endpoint

### GET /api/graph
Full trust graph for visualization.

**Response (200):**
```json
{
  "nodes": [
    {
      "id": "uuid",
      "username": "peter",
      "display_name": "Peter Johnson",
      "bio": "Licensed electrician"
    }
  ],
  "edges": [
    {
      "source": "uuid (peter)",
      "target": "uuid (molly)"
    }
  ],
  "networks": [
    {
      "id": "uuid",
      "name": "The Johnsons",
      "network_type": "family",
      "members": ["uuid (peter)", "uuid (molly)", "uuid (jane)", "uuid (bill)"]
    }
  ]
}
```

---

## Health Check

### GET /health

**Response (200):**
```json
{
  "status": "ok",
  "service": "trustmesh-core"
}
```
