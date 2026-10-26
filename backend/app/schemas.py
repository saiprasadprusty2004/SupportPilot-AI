from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class KnowledgeArguments(ToolArguments):
    query: str = Field(min_length=2, max_length=2000)


class TicketArguments(ToolArguments):
    ticket_id: str = Field(min_length=1, max_length=36)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class AcceptInvite(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=200)


class InviteInput(BaseModel):
    email: EmailStr
    role: Literal["agent", "owner"] = "agent"


class ResetInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=200)


class ConnectInput(BaseModel):
    provider: Literal["gmail", "slack", "googledrive"]


class ConnectionUpdate(BaseModel):
    automation_enabled: bool
    approval_policy_accepted: bool = False
    label: str = Field(default="INBOX", min_length=1, max_length=100)


class RunInput(BaseModel):
    prompt: str = Field(min_length=3, max_length=8000)
    ticket_id: str | None = None


class ReplyArguments(ToolArguments):
    to: EmailStr
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=12000)
    thread_id: str = Field(min_length=1, max_length=255)

    @field_validator("subject")
    @classmethod
    def no_header_injection(cls, value):
        if "\n" in value or "\r" in value:
            raise ValueError("Subject must be a single line")
        return value


class SlackArguments(ToolArguments):
    channel: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1, max_length=12000)


class RefundArguments(ToolArguments):
    payment_id: str = Field(pattern=r"^pi_[A-Za-z0-9_]+$", max_length=100)
    amount: int = Field(gt=0, le=999999999)
    currency: str = Field(pattern=r"^[a-z]{3}$")
    reason: Literal["requested_by_customer", "duplicate", "fraudulent"] = "requested_by_customer"


ACTION_SCHEMAS = {
    "gmail_reply": ReplyArguments,
    "slack_escalation": SlackArguments,
    "stripe_refund": RefundArguments,
}


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject", "edit"]
    version: int = Field(ge=1)
    arguments: dict | None = None


class ReconcileInput(BaseModel):
    outcome: Literal["confirmed_sent", "confirmed_not_sent"]
    evidence: str = Field(min_length=10, max_length=2000)
    provider_reference: str = Field(default="", max_length=255)


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=2000)


class DriveImport(BaseModel):
    file_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=255)
    publish_to_workspace: bool


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slack_channel: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_-]*$")


class StripeKeyInput(BaseModel):
    key: str = Field(pattern=r"^(sk|rk)_test_[A-Za-z0-9]+$", max_length=255)


class PaymentLink(BaseModel):
    payment_id: str = Field(pattern=r"^pi_[A-Za-z0-9_]+$", max_length=100)
