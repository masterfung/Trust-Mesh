"""Pydantic schemas for API request/response validation."""

import json
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ── Users ──────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    bio: str = ""
    user_type: str = "person"  # "person" | "service"
    is_discoverable: bool = True
    password: str = Field(min_length=16, max_length=128)
    agent_personality: str | None = None

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        """Require uppercase, lowercase, digit, and special character."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(not c.isalnum() for c in v):
            raise ValueError("Password must contain at least one special character (!@#$%^&* etc.)")
        return v


class ProfileData(BaseModel):
    occupation: dict | None = None  # {"title": str, "industry": str}
    skills: list[dict] = []  # [{"name": str, "category": str}]
    interests: list[dict] = []  # [{"name": str, "category": str}]
    family_status: str | None = None
    age_range: str | None = None
    location_hints: list[str] = []


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    bio: str
    user_type: str = "person"
    profile_data: dict | None = None
    is_discoverable: bool
    is_demo: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("profile_data", mode="before")
    @classmethod
    def parse_profile_data(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v


class UserPublic(BaseModel):
    id: str
    username: str
    display_name: str
    bio: str
    user_type: str = "person"
    profile_data: dict | None = None

    model_config = {"from_attributes": True}

    @field_validator("profile_data", mode="before")
    @classmethod
    def parse_profile_data(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    user: UserResponse
    token: str


# ── Agents ─────────────────────────────────────────

class AgentResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    personality: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentSkillSchema(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = []


class AgentCard(BaseModel):
    """A2A-compatible agent card."""
    name: str
    description: str
    url: str = ""
    version: str = "1.0.0"
    owner: UserPublic
    public_key_b64: str | None = None
    did: str | None = None
    capabilities: list[str] = ["knowledge-query", "trust-aware-sharing"]
    skills: list[AgentSkillSchema] = []
    default_input_modes: list[str] = ["text"]
    default_output_modes: list[str] = ["text"]
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
    is_public: bool = False
    join_policy: str = "invite_only"


class NetworkResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str
    network_type: str
    is_public: bool = False
    join_policy: str = "invite_only"
    created_at: datetime
    members: list[UserPublic] = []

    model_config = {"from_attributes": True}


class NetworkDiscoveryResponse(BaseModel):
    id: str
    name: str
    description: str
    network_type: str
    join_policy: str
    member_count: int
    owner_name: str


class NetworkJoinRequestCreate(BaseModel):
    message: str = ""


class NetworkJoinRequestResponse(BaseModel):
    id: str
    user_id: str
    network_id: str
    message: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None = None
    user: UserPublic | None = None

    model_config = {"from_attributes": True}


class NetworkJoinRequestUpdate(BaseModel):
    status: str = Field(pattern=r"^(approved|declined)$")


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
    capsule_type: str | None = None
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

class ConversationMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str


class QueryCreate(BaseModel):
    from_user_id: str
    to_user_id: str
    question: str = Field(min_length=1)
    conversation_history: list[ConversationMessage] | None = None


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
    user_type: str = "person"
    profile_data: dict | None = None


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


# ── Agent Tasks ───────────────────────────────────

class AgentTaskResponse(BaseModel):
    id: str
    owner_id: str
    title: str
    description: str
    status: str
    task_type: str
    result: str | None = None
    source_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Notifications ─────────────────────────────────

class NotificationResponse(BaseModel):
    id: str
    user_id: str
    notification_type: str
    title: str
    body: str
    is_read: bool
    related_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Services ──────────────────────────────────────

class ServiceCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    bio: str = ""
    agent_personality: str = ""
    password: str = Field(min_length=16, max_length=128)
    skills: list[AgentSkillSchema] = []
    capsules: list[dict] = []  # [{type, title, content, tier}]


class ServiceResponse(BaseModel):
    id: str
    username: str
    display_name: str
    bio: str
    user_type: str = "service"
    profile_data: dict | None = None
    agent_card: AgentCard | None = None

    model_config = {"from_attributes": True}


# ── Briefing ──────────────────────────────────────

class BriefingResponse(BaseModel):
    user_id: str
    briefing: str
    generated_at: datetime
    sections: dict = {}  # {schedule: [...], tasks: [...], network_updates: [...]}


# ── Audit ────────────────────────────────────────

class AuditLogResponse(BaseModel):
    id: str
    actor_user_id: str | None = None
    actor_did: str | None = None
    actor_role: str | None = None
    actor_institution: str | None = None
    target_user_id: str | None = None
    action: str
    event_type: str
    capsule_ids_accessed: list[str] = []
    categories_accessed: list[str] = []
    token_hash: str | None = None
    token_role: str | None = None
    token_expires_at: datetime | None = None
    case_id: str | None = None
    reason: str | None = None
    query_id: str | None = None
    decision: str = "allowed"
    details: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("capsule_ids_accessed", mode="before")
    @classmethod
    def parse_capsule_ids(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v or []

    @field_validator("categories_accessed", mode="before")
    @classmethod
    def parse_categories(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v or []

    @field_validator("details", mode="before")
    @classmethod
    def parse_details(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v


# ── Emergency ────────────────────────────────────

class EmergencyRoleInfo(BaseModel):
    role: str
    categories: list[str]
    keywords: list[str]


class EmergencyTokenRequest(BaseModel):
    issuer_user_id: str
    patient_username: str
    role: str
    duration_seconds: int = Field(default=3600, ge=-1, le=3600)  # Max 1 hour; -1 for testing expired tokens
    practitioner_name: str = ""
    npi: str = ""
    case_id: str = ""
    reason: str = ""


class EmergencyTokenResponse(BaseModel):
    token: str
    issuer_did: str
    audience_did: str
    role: str
    expires_in: int
    scope: EmergencyRoleInfo


class EmergencyAccessRequest(BaseModel):
    token: str
    patient_username: str


class EmergencyAccessResponse(BaseModel):
    patient_name: str
    role: str
    capsules: list[dict]
    capsule_count: int
    categories: list[str]
    audit_id: str
    expires_at: datetime
