"""Pydantic schemas for API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


# ── Users ──────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    bio: str = ""
    is_discoverable: bool = True
    password: str = Field(min_length=4, max_length=100)  # Simplified for hackathon


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    bio: str
    is_discoverable: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserPublic(BaseModel):
    id: str
    username: str
    display_name: str
    bio: str

    model_config = {"from_attributes": True}


# ── Agents ─────────────────────────────────────────

class AgentResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    personality: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentCard(BaseModel):
    """A2A-compatible agent card."""
    name: str
    description: str
    owner: UserPublic
    capabilities: list[str] = ["knowledge-query", "trust-aware-sharing"]
    protocol: str = "trustmesh/1.0"


# ── Connections ────────────────────────────────────

class ConnectionRequestCreate(BaseModel):
    from_user_id: str
    to_user_id: str
    message: str = ""


class ConnectionRequestResponse(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    message: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None = None
    from_user: UserPublic | None = None
    to_user: UserPublic | None = None

    model_config = {"from_attributes": True}


class ConnectionRequestUpdate(BaseModel):
    status: str = Field(pattern=r"^(accepted|declined)$")


class ConnectionResponse(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    status: str
    created_at: datetime
    accepted_at: datetime | None = None
    peer: UserPublic | None = None

    model_config = {"from_attributes": True}


# ── Networks ───────────────────────────────────────

class NetworkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    network_type: str = "custom"
    owner_id: str


class NetworkResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str
    network_type: str
    created_at: datetime
    members: list[UserPublic] = []

    model_config = {"from_attributes": True}


class NetworkAddMember(BaseModel):
    user_id: str


# ── Knowledge Capsules ─────────────────────────────

class CapsuleCreate(BaseModel):
    capsule_type: str = Field(pattern=r"^(memory|skill|procedure|schedule|preference|contact)$")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    tier: str = Field(default="private", pattern=r"^(public|network|private)$")
    category: str = ""
    freshness: str = "permanent"
    expires_at: datetime | None = None
    auto_archive_days: int | None = None
    network_ids: list[str] = []


class CapsuleUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tier: str | None = None
    category: str | None = None
    freshness: str | None = None
    expires_at: datetime | None = None
    auto_archive_days: int | None = None
    network_ids: list[str] | None = None


class CapsuleResponse(BaseModel):
    id: str
    owner_id: str
    capsule_type: str
    title: str
    content: str  # Decrypted for owner view
    tier: str
    category: str
    freshness: str
    expires_at: datetime | None = None
    last_verified_at: datetime
    auto_archive_days: int | None = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    network_ids: list[str] = []

    model_config = {"from_attributes": True}


class CapsuleShareRequest(BaseModel):
    network_ids: list[str]


# ── Queries ────────────────────────────────────────

class QueryCreate(BaseModel):
    from_user_id: str
    to_user_id: str
    question: str = Field(min_length=1)


class CitadelResult(BaseModel):
    score: float | None = None
    decision: str | None = None
    is_safe: bool | None = None
    findings: list[str] | None = None


class QueryResponse(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    question: str
    trust_level: str
    shared_networks: list[str] = []
    response: str | None = None
    decision: str
    citadel_input: CitadelResult | None = None
    citadel_output: CitadelResult | None = None
    latency_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Graph ──────────────────────────────────────────

class GraphNode(BaseModel):
    id: str
    username: str
    display_name: str
    bio: str


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str = "connection"


class GraphNetwork(BaseModel):
    id: str
    name: str
    network_type: str
    members: list[str]


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    networks: list[GraphNetwork]
