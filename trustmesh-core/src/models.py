"""SQLAlchemy models for TrustMesh."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
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
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bio: Mapped[str] = mapped_column(Text, default="")
    user_type: Mapped[str] = mapped_column(String(20), default="person")  # "person" | "service"
    profile_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON structured profile
    is_discoverable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    vault_key_salt: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_vault_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
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
    encrypted_network_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
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
    tier: Mapped[str] = mapped_column(String(20), default="private")
    category: Mapped[str] = mapped_column(String(50), default="")
    context: Mapped[str] = mapped_column(String(20), default="personal")  # work | personal | both
    freshness: Mapped[str] = mapped_column(String(20), default="permanent")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    auto_archive_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped["User"] = relationship(back_populates="capsules")
    network_access: Mapped[list["CapsuleNetworkAccess"]] = relationship(
        back_populates="capsule", cascade="all, delete-orphan"
    )


class CapsuleNetworkAccess(Base):
    __tablename__ = "capsule_network_access"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    capsule_id: Mapped[str] = mapped_column(ForeignKey("knowledge_capsules.id"), nullable=False)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), nullable=False)

    capsule: Mapped["KnowledgeCapsule"] = relationship(back_populates="network_access")
    network: Mapped["Network"] = relationship(back_populates="capsule_access")


class ConnectionRequest(Base):
    __tablename__ = "connection_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    from_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
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
