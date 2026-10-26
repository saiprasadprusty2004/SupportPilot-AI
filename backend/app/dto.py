"""Public response contracts, exported to TypeScript through OpenAPI."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict


class PublicRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: float


class CitationOut(BaseModel):
    chunk_id: str
    document_id: str
    name: str
    page: int
    excerpt: str
    version: int
    url: str
    score: float = 0


class RunOut(PublicRecord):
    prompt: str
    status: str
    current_node: str
    result: str | None
    error: str | None
    citations: list[CitationOut]
    updated_at: float
    ticket_id: str | None


class ActionOut(PublicRecord):
    run_id: str
    kind: str
    arguments: dict[str, str | int]
    status: str
    version: int
    rationale: str
    citations: list[CitationOut]
    expires_at: float
    acting_account_label: str | None = None


class TicketOut(PublicRecord):
    subject: str
    sender: str
    preview: str
    status: str
    priority: str
    updated_at: float
    payment_id: str | None
    connection_id: str


class DocumentOut(PublicRecord):
    name: str
    status: str
    size: int
    version: int
    error: str | None
    source_url: str | None
    embedding_config: dict[str, Any]


class ConnectionOut(PublicRecord):
    provider: str
    account_email: str
    status: str
    automation_enabled: bool
    label: str
    user_id: str


class EventOut(PublicRecord):
    sequence: int
    node: str
    status: str
    duration_ms: int | None
    data: dict[str, Any]


class UserOut(BaseModel):
    id: str
    name: str
    email: str


class WorkspaceMembershipOut(BaseModel):
    id: str
    name: str
    role: str


class SessionOut(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceMembershipOut]
    csrf_token: str
    demo_mode: bool


T = TypeVar("T")


class PageOut(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
