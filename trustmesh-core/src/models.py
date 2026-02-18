"""SQLAlchemy models for TrustMesh."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


def parse_profile_data(raw) -> dict | None:
    """Parse profile_data from DB (stored as JSON string) into a dict. DRY helper."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    return raw


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)  # Public handle — set on "Go Live", NULL for private users
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # base64 data URI or external URL
    user_type: Mapped[str] = mapped_column(String(20), default="person")  # "person" | "organization" | "government"
    profile_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON structured profile
    is_discoverable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    remote_pod_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remote_did: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vault_key_salt: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_vault_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Argon2id hashed PIN
    agent_personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_context: Mapped[str] = mapped_column(String(20), default="all")  # work | personal | all
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    agent: Mapped["Agent | None"] = relationship(back_populates="owner", uselist=False)
    capsules: Mapped[list["KnowledgeCapsule"]] = relationship(back_populates="owner")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    personality: Mapped[str] = mapped_column(Text, default="Helpful and knowledgeable")
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_private_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    did: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped["User"] = relationship(back_populates="agent")


class Network(Base):
    __tablename__ = "networks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    network_type: Mapped[str] = mapped_column(String(20), default="custom")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    join_policy: Mapped[str] = mapped_column(String(20), default="invite_only")  # invite_only | request_to_join | open
    context: Mapped[str] = mapped_column(String(20), default="personal")  # work | personal | both
    pool_type: Mapped[str] = mapped_column(String(20), default="standard")  # standard | category_scoped | public_registry
    shared_categories: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of categories
    encrypted_network_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["NetworkMembership"]] = relationship(back_populates="network")
    capsule_access: Mapped[list["CapsuleNetworkAccess"]] = relationship(back_populates="network")


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    from_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    context: Mapped[str] = mapped_column(String(20), default="personal")  # work | personal | both
    status: Mapped[str] = mapped_column(String(20), default="pending")
    relationship_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # family|friend|work|healthcare|neighbor|emergency|other
    from_label: Mapped[str | None] = mapped_column(String(50), nullable=True)  # from_user's label for to_user
    to_label: Mapped[str | None] = mapped_column(String(50), nullable=True)    # to_user's label for from_user
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NetworkMembership(Base):
    __tablename__ = "network_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member")
    encrypted_network_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    network: Mapped["Network"] = relationship(back_populates="memberships")


class KnowledgeCapsule(Base):
    __tablename__ = "knowledge_capsules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    capsule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    # Data governance: 4-level visibility model
    visibility: Mapped[str] = mapped_column(String(20), default="private")  # private | internal | shareable | open
    emergency_accessible: Mapped[bool] = mapped_column(Boolean, default=False)
    can_reshare: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String(50), default="")
    embedding_collection: Mapped[str] = mapped_column(String(50), default="general")
    context: Mapped[str] = mapped_column(String(20), default="personal")  # work | personal | both
    freshness: Mapped[str] = mapped_column(String(20), default="permanent")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    auto_archive_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    authority_weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped["User"] = relationship(back_populates="capsules")
    network_access: Mapped[list["CapsuleNetworkAccess"]] = relationship(
        back_populates="capsule", cascade="all, delete-orphan"
    )
    share_grants: Mapped[list["CapsuleShareGrant"]] = relationship(
        back_populates="capsule", cascade="all, delete-orphan"
    )

    @property
    def tier(self) -> str:
        """Backward-compat alias: maps visibility to old tier names."""
        return {"private": "private", "internal": "network", "shareable": "network", "open": "public"}.get(
            self.visibility, "private"
        )

    @tier.setter
    def tier(self, value: str):
        """Backward-compat setter: maps old tier names to visibility."""
        self.visibility = {"private": "private", "network": "internal", "public": "open"}.get(value, value)


class CapsuleNetworkAccess(Base):
    __tablename__ = "capsule_network_access"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    capsule_id: Mapped[str] = mapped_column(ForeignKey("knowledge_capsules.id"), nullable=False)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), nullable=False)

    capsule: Mapped["KnowledgeCapsule"] = relationship(back_populates="network_access")
    network: Mapped["Network"] = relationship(back_populates="capsule_access")


class CapsuleShareGrant(Base):
    """Explicit share grants for 'shareable' visibility capsules."""
    __tablename__ = "capsule_share_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    capsule_id: Mapped[str] = mapped_column(ForeignKey("knowledge_capsules.id"), nullable=False)
    grantee_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    grantee_network_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    can_reshare: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[str] = mapped_column(String(36), nullable=False)  # user_id of granter
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    capsule: Mapped["KnowledgeCapsule"] = relationship(back_populates="share_grants")


class SharingDelegate(Base):
    """Delegate authority: owner grants another user power to manage sharing for specific categories."""
    __tablename__ = "sharing_delegates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    delegate_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "health", "work", "*"
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectionRequest(Base):
    __tablename__ = "connection_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    from_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    relationship_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    from_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    from_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    trust_level: Mapped[str] = mapped_column(String(20), default="public")
    shared_networks: Mapped[str] = mapped_column(Text, default="[]")
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str] = mapped_column(String(20), default="allowed")
    citadel_input_score: Mapped[float | None] = mapped_column(nullable=True)
    citadel_input_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    citadel_output_safe: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    citadel_output_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | in_progress | completed | failed
    task_type: Mapped[str] = mapped_column(String(20), default="search")  # search | compare | compile | follow_up
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON result
    source_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(30), nullable=False)  # query_received | task_completed | connection_request | quote_received
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    related_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NetworkJoinRequest(Base):
    __tablename__ = "network_join_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | declined
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_did: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_institution: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # emergency | query | auth | capsule
    capsule_ids_accessed: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    categories_accessed: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decision: Mapped[str] = mapped_column(String(20), default="allowed")  # allowed | denied
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CapsuleVersion(Base):
    """Version history for capsule changes (audit trail)."""
    __tablename__ = "capsule_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    capsule_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(36), nullable=False)
    changed_fields: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: {"field": {"old": x, "new": y}}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UCANRevocation(Base):
    """Revoked UCAN tokens — checked during token validation."""
    __tablename__ = "ucan_revocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    revoked_by: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PeerPod(Base):
    """A known peer TrustMesh pod that this pod can federate with."""
    __tablename__ = "peer_pods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | unreachable
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NetworkInvite(Base):
    __tablename__ = "network_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), nullable=False)
    invited_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted | expired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PoolInviteToken(Base):
    """One-time tokens for cross-pod pool invitations."""
    __tablename__ = "pool_invite_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    target_pod_url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | consumed | expired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
