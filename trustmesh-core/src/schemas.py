"""Pydantic schemas for API request/response validation."""

import json
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ── Users ──────────────────────────────────────────

ORG_SUBTYPES = ("company", "nonprofit", "healthcare", "education", "emergency", "government")


class UserCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    bio: str = Field(default="", max_length=5000)
    user_type: str = "person"  # "person" | "organization"
    org_subtype: str | None = Field(default=None, max_length=20)  # only for organizations
    is_discoverable: bool = False
    password: str = Field(min_length=16, max_length=128)
    agent_personality: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=512_000)
    # Username is optional at signup — auto-generated if not provided.
    # Public handle is claimed later via Go Live.
    username: str | None = Field(default=None, min_length=2, max_length=50)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        """Names must be alphabetic (letters, spaces, hyphens, apostrophes, periods).
        Orgs can be single-word — the check is a bit more permissive."""
        import re
        if not re.match(r"^[A-Za-z][A-Za-z0-9 \-'&.,]+$", v.strip()):
            raise ValueError("Name must contain only letters, spaces, hyphens, and apostrophes")
        return v.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        import re
        v = v.strip().lower()
        if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("user_type")
    @classmethod
    def validate_user_type(cls, v: str) -> str:
        # "government" is accepted for backward compat — routes normalize it to organization+subtype
        allowed = ("person", "organization", "government")
        if v not in allowed:
            raise ValueError(f"user_type must be one of {allowed}")
        return v

    @field_validator("org_subtype")
    @classmethod
    def validate_org_subtype(cls, v: str | None) -> str | None:
        if v is not None and v not in ORG_SUBTYPES:
            raise ValueError(f"org_subtype must be one of {ORG_SUBTYPES}")
        return v

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


class ContextSwitch(BaseModel):
    context: str = Field(pattern=r"^(work|personal|all)$")


class AgentModeUpdate(BaseModel):
    mode: str  # "public" | "internal"


class UserResponse(BaseModel):
    id: str
    username: str | None = None  # NULL for private users, set on Go Live
    email: str | None = None
    display_name: str
    bio: str
    user_type: str = "person"
    org_subtype: str | None = None
    agent_mode: str = "private"
    profile_data: dict | None = None
    is_discoverable: bool
    is_demo: bool = False
    is_remote: bool = False
    active_context: str = "all"
    avatar_url: str | None = None
    connectivity_mode: str = "invite_only"
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
    username: str | None = None
    display_name: str
    bio: str
    user_type: str = "person"
    profile_data: dict | None = None
    avatar_url: str | None = None

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
    # Accepts display_name, username, or email
    username: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    password: str = Field(max_length=128)


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

VALID_RELATIONSHIP_TYPES = {"family", "friend", "work", "healthcare", "neighbor", "emergency", "other"}


class ConnectionRequestCreate(BaseModel):
    from_user_id: str
    to_user_id: str
    message: str = Field(default="", max_length=500)
    context: str = "personal"  # work | personal | both
    relationship_type: str | None = None
    from_label: str | None = Field(default=None, max_length=50)

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_RELATIONSHIP_TYPES:
            raise ValueError(f"relationship_type must be one of {sorted(VALID_RELATIONSHIP_TYPES)}")
        return v


class ConnectionRequestResponse(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    message: str
    status: str
    context: str = "personal"
    relationship_type: str | None = None
    from_label: str | None = None
    mutual_connections: int = 0
    mutual_networks: int = 0
    created_at: datetime
    reviewed_at: datetime | None = None
    from_user: UserPublic | None = None
    to_user: UserPublic | None = None

    model_config = {"from_attributes": True}


class ConnectionRequestUpdate(BaseModel):
    status: str = Field(pattern=r"^(accepted|declined)$")
    to_label: str | None = Field(default=None, max_length=50)


class ConnectionLabelUpdate(BaseModel):
    my_label: str | None = Field(default=None, max_length=50)
    relationship_type: str | None = None
    context: str | None = Field(default=None, pattern=r"^(work|personal|both)$")

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_RELATIONSHIP_TYPES:
            raise ValueError(f"relationship_type must be one of {sorted(VALID_RELATIONSHIP_TYPES)}")
        return v


class ConnectionResponse(BaseModel):
    id: str
    from_user_id: str
    to_user_id: str
    status: str
    context: str = "personal"
    relationship_type: str | None = None
    my_label: str | None = None
    peer_label: str | None = None
    created_at: datetime
    accepted_at: datetime | None = None
    peer: UserPublic | None = None

    model_config = {"from_attributes": True}


# ── Networks ───────────────────────────────────────

class NetworkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    network_type: str = "custom"
    owner_id: str
    is_public: bool = False
    join_policy: str = "invite_only"
    context: str = "personal"  # work | personal | both
    pool_type: str = "standard"  # standard | category_scoped | public_registry | org_all_staff | org_executives
    shared_categories: list[str] | None = None
    expires_at: datetime | None = None
    initial_member_ids: list[str] | None = None


class NetworkResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    description: str
    network_type: str
    is_public: bool = False
    join_policy: str = "invite_only"
    context: str = "personal"
    pool_type: str = "standard"
    shared_categories: list[str] | None = None
    expires_at: datetime | None = None
    created_at: datetime
    members: list[UserPublic] = []

    model_config = {"from_attributes": True}

    @field_validator("shared_categories", mode="before")
    @classmethod
    def parse_shared_categories(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v


class NetworkDiscoveryResponse(BaseModel):
    id: str
    name: str
    description: str
    network_type: str
    join_policy: str
    context: str = "personal"
    pool_type: str = "standard"
    shared_categories: list[str] | None = None
    member_count: int
    owner_name: str


class NetworkJoinRequestCreate(BaseModel):
    message: str = Field(default="", max_length=500)


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
    content: str = Field(min_length=1, max_length=100000)
    # Governance: accept both old tier and new visibility
    tier: str | None = Field(default=None, pattern=r"^(public|network|private)$")
    visibility: str = Field(default="private", pattern=r"^(private|internal|shareable|open)$")
    emergency_accessible: bool = False
    can_reshare: bool = False
    category: str = Field(default="", max_length=100)
    context: str = "personal"  # work | personal | both
    freshness: str = "permanent"
    expires_at: datetime | None = None
    auto_archive_days: int | None = None
    network_ids: list[str] = []
    supersedes_id: str | None = None

    def effective_visibility(self) -> str:
        """Map old tier to new visibility if tier was provided."""
        if self.tier is not None:
            return {"private": "private", "network": "internal", "public": "open"}.get(self.tier, self.visibility)
        return self.visibility


class CapsuleUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=100000)
    capsule_type: str | None = Field(default=None, pattern=r"^(memory|skill|procedure|schedule|preference|contact)$")
    tier: str | None = Field(default=None, pattern=r"^(public|network|private)$")
    visibility: str | None = Field(default=None, pattern=r"^(private|internal|shareable|open)$")
    emergency_accessible: bool | None = None
    can_reshare: bool | None = None
    category: str | None = Field(default=None, max_length=100)
    context: str | None = Field(default=None, pattern=r"^(work|personal|both)$")
    freshness: str | None = Field(default=None, max_length=50)
    expires_at: datetime | None = None
    auto_archive_days: int | None = Field(default=None, ge=1, le=365)
    network_ids: list[str] | None = None
    supersedes_id: str | None = None

    def effective_visibility(self) -> str | None:
        """Map old tier to new visibility if tier was provided."""
        if self.visibility is not None:
            return self.visibility
        if self.tier is not None:
            return {"private": "private", "network": "internal", "public": "open"}.get(self.tier, self.tier)
        return None


class CapsuleResponse(BaseModel):
    id: str
    owner_id: str
    owner_display_name: str | None = None
    capsule_type: str
    title: str
    content: str  # Decrypted for owner view
    tier: str  # backward-compat alias
    visibility: str = "private"
    emergency_accessible: bool = False
    can_reshare: bool = False
    category: str
    context: str = "personal"
    freshness: str
    expires_at: datetime | None = None
    last_verified_at: datetime
    auto_archive_days: int | None = None
    is_archived: bool
    supersedes_id: str | None = None
    authority_weight: float = 1.0
    created_at: datetime
    updated_at: datetime
    network_ids: list[str] = []
    network_names: list[str] = []

    model_config = {"from_attributes": True}


class CapsuleShareRequest(BaseModel):
    network_ids: list[str]


# ── Share Grants (for shareable visibility) ───────

class ShareGrantCreate(BaseModel):
    capsule_id: str
    grantee_user_id: str | None = None
    grantee_network_id: str | None = None
    can_reshare: bool = False
    expires_in_days: int = Field(default=30, ge=1, le=365)

class ShareGrantResponse(BaseModel):
    id: str
    capsule_id: str
    grantee_user_id: str | None = None
    grantee_network_id: str | None = None
    can_reshare: bool
    expires_at: datetime | None = None
    granted_by: str
    granted_at: datetime

    model_config = {"from_attributes": True}


# ── Sharing Delegates ────────────────────────────

class DelegateCreate(BaseModel):
    delegate_user_id: str
    category: str = Field(max_length=50)

class DelegateResponse(BaseModel):
    id: str
    owner_id: str
    delegate_user_id: str
    category: str
    granted_at: datetime
    revoked_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── PIN ──────────────────────────────────────────

class PinSetRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{6,8}$")

class PinVerifyRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{6,8}$")

class PinVerifyResponse(BaseModel):
    verified: bool
    token: str | None = None
    expires_in: int = 300  # 5 minutes

class PinStatusResponse(BaseModel):
    has_pin: bool


# ── Queries ────────────────────────────────────────

class ConversationMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(max_length=50000)


class QueryCreate(BaseModel):
    from_user_id: str
    to_user_id: str
    question: str = Field(min_length=1, max_length=10000)
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
    username: str | None = None
    display_name: str
    bio: str | None = None
    user_type: str = "person"
    profile_data: dict | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str = "connection"


class GraphNetwork(BaseModel):
    id: str
    name: str
    network_type: str | None = None
    pool_type: str | None = "standard"
    shared_categories: list[str] | None = None
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
    bio: str = Field(default="", max_length=5000)
    agent_personality: str = Field(default="", max_length=1000)
    password: str = Field(min_length=16, max_length=128)
    skills: list[AgentSkillSchema] = Field(default=[], max_length=50)
    capsules: list[dict] = Field(default=[], max_length=100)


class ServiceResponse(BaseModel):
    id: str
    username: str | None = None
    display_name: str
    bio: str
    user_type: str = "organization"
    org_subtype: str | None = None
    agent_mode: str = "public"
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
    role: str = Field(pattern=r"^(attending_physician|er_nurse|paramedic|admin)$")
    duration_seconds: int = Field(default=3600, ge=-1, le=3600)  # Max 1 hour; -1 for testing expired tokens
    practitioner_name: str = Field(default="", max_length=200)
    npi: str = Field(default="", max_length=20)
    case_id: str = Field(default="", max_length=100)
    reason: str = Field(default="", max_length=500)


class EmergencyTokenResponse(BaseModel):
    token: str
    issuer_did: str
    audience_did: str
    role: str
    expires_in: int
    scope: EmergencyRoleInfo


class EmergencyAccessRequest(BaseModel):
    token: str = Field(max_length=4096)
    patient_username: str = Field(max_length=50)


class EmergencyBeaconResponse(BaseModel):
    tokens: dict[str, str]    # role → signed UCAN token
    qr_urls: dict[str, str]   # role → full QR scan URL
    patient_did: str
    patient_name: str
    pod_url: str
    expires_in: int           # seconds (1800)
    generated_at: str         # ISO-8601 timestamp
    audit_id: str


class EmergencyAccessResponse(BaseModel):
    patient_name: str
    role: str
    capsules: list[dict]
    capsule_count: int
    total_capsules: int = 0
    categories: list[str]
    audit_id: str
    expires_at: datetime
    family_notified: int = 0
    fhir_bundle_url: str | None = None


class MessageResponse(BaseModel):
    id: str
    sender_id: str
    sender_username: str
    sender_display_name: str
    sender_pod_url: str | None = None
    recipient_id: str
    subject: str
    body: str | None = None  # Decrypted body (None if vault key unavailable)
    scope: str
    trust_level_at_send: str
    expires_at: datetime | None = None
    rekey_needed: bool = False
    is_read: bool = False
    read_at: datetime | None = None
    created_at: datetime


class MessageUnreadCount(BaseModel):
    count: int
