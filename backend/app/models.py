from datetime import datetime, timezone
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).timestamp()


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[float] = mapped_column(Float, default=now, index=True)


class Tenant:
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), index=True)


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(Text)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)


class Workspace(Record, Base):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(String(100))
    stripe_key_ciphertext: Mapped[str | None] = mapped_column(Text)
    slack_channel: Mapped[str] = mapped_column(String(100), default="")


class Membership(Record, Tenant, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="agent")


class AuthSession(Record, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float)


class OneTimeToken(Record, Base):
    __tablename__ = "one_time_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(254))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    role: Mapped[str] = mapped_column(String(20), default="agent")
    expires_at: Mapped[float] = mapped_column(Float)
    used_at: Mapped[float | None] = mapped_column(Float)


class OAuthAttempt(Record, Base):
    __tablename__ = "oauth_attempts"
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    nonce: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[float] = mapped_column(Float)


class Connection(Record, Tenant, Base):
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", "provider"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    account_id: Mapped[str] = mapped_column(String(100))
    account_email: Mapped[str] = mapped_column(String(254), default="")
    status: Mapped[str] = mapped_column(String(30), default="active")
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[str] = mapped_column(String(100), default="INBOX")
    sync_cursor: Mapped[str | None] = mapped_column(Text)
    sync_started_at: Mapped[float | None] = mapped_column(Float)
    synced_at: Mapped[float | None] = mapped_column(Float)


class Document(Record, Tenant, Base):
    __tablename__ = "documents"
    name: Mapped[str] = mapped_column(String(255))
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    storage_key: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    version: Mapped[int] = mapped_column(Integer, default=1)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(String(255))
    connection_id: Mapped[str | None] = mapped_column(ForeignKey("connections.id"))
    error: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    embedding_config: Mapped[dict] = mapped_column(JSON, default=dict)
    deleted_at: Mapped[float | None] = mapped_column(Float)


class DocumentVersion(Record, Tenant, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    storage_key: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))


class Chunk(Record, Tenant, Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_document_version", "document_id", "version"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str] = mapped_column(String(255), default="")
    embedding: Mapped[list] = mapped_column(JSON().with_variant(Vector(384), "postgresql"))


class Ticket(Record, Tenant, Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("connection_id", "provider_thread_id"),)
    connection_id: Mapped[str] = mapped_column(ForeignKey("connections.id"))
    provider_thread_id: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(500))
    sender: Mapped[str] = mapped_column(String(254))
    preview: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="open")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    updated_at: Mapped[float] = mapped_column(Float, default=now)
    payment_id: Mapped[str | None] = mapped_column(String(100))


class Message(Record, Tenant, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("connection_id", "provider_message_id"),)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("connections.id"))
    provider_message_id: Mapped[str] = mapped_column(String(255))
    sender: Mapped[str] = mapped_column(String(254))
    body: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(10), default="inbound")


class Run(Record, Tenant, Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    current_node: Mapped[str] = mapped_column(String(50), default="queued")
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[float] = mapped_column(Float, default=now)
    completed_at: Mapped[float | None] = mapped_column(Float)


class RunEvent(Record, Tenant, Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Action(Record, Tenant, Base):
    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("run_id", "version"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    connection_id: Mapped[str | None] = mapped_column(ForeignKey("connections.id"))
    arguments: Mapped[dict] = mapped_column(JSON)
    provider_account_id: Mapped[str | None] = mapped_column(String(255))
    acting_account_label: Mapped[str | None] = mapped_column(String(254))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    rationale: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    ticket_updated_at: Mapped[float | None] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[float | None] = mapped_column(Float)


class ToolExecution(Record, Tenant, Base):
    __tablename__ = "tool_executions"
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="prepared")
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Job(Record, Tenant, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_dispatch", "status", "available_at"),)
    kind: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[float] = mapped_column(Float, default=now)
    lease_until: Mapped[float | None] = mapped_column(Float)
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    last_error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class JobAttempt(Record, Tenant, Base):
    __tablename__ = "job_attempts"
    __table_args__ = (UniqueConstraint("job_id", "number"),)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    lease_owner: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30), default="running")
    finished_at: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class Outbox(Record, Tenant, Base):
    __tablename__ = "outbox"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    published_at: Mapped[float | None] = mapped_column(Float)


class Audit(Record, Tenant, Base):
    __tablename__ = "audit"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    event: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[float] = mapped_column(Float)
