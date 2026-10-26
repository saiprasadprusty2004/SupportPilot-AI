import re

from sqlalchemy import select, update

from app.models import (
    Action,
    Audit,
    Connection,
    Document,
    Membership,
    Message,
    Run,
    Ticket,
    ToolExecution,
    Workspace,
    now,
)
from app.schemas import ACTION_SCHEMAS
from app.security import payload_hash, redact, tenant_get
from app.services.events import TOOLS, emit
from app.services.providers import Composio, ProviderError, Stripe


class ReapprovalRequired(Exception):
    pass


def latest_action(db, run):
    return db.scalar(
        select(Action)
        .where(Action.run_id == run.id, Action.workspace_id == run.workspace_id)
        .order_by(Action.version.desc())
        .limit(1)
    )


def actor_connection(db, run, provider):
    connection = db.scalar(
        select(Connection).where(
            Connection.workspace_id == run.workspace_id,
            Connection.user_id == run.user_id,
            Connection.provider == provider,
            Connection.status == "active",
        )
    )
    if not connection or not connection.automation_enabled:
        raise ValueError(f"Connect {provider} and enable its workspace approval policy first")
    return connection


def normalized_subject(value):
    return re.sub(r"^(re:\s*)+", "", value, flags=re.I).strip()


def acting_account(db, run, connection):
    if connection:
        return connection.account_id, connection.account_email or connection.provider + " personal account"
    workspace = db.get(Workspace, run.workspace_id)
    return payload_hash(workspace.stripe_key_ciphertext or "unconfigured"), "Workspace Stripe test account"


def validate_proposal(db, run, kind, arguments):
    arguments = ACTION_SCHEMAS[kind].model_validate(arguments).model_dump(mode="json")
    ticket = tenant_get(db, Ticket, run.ticket_id, run.workspace_id) if run.ticket_id else None
    connection = None
    if kind == "gmail_reply":
        connection = actor_connection(db, run, "gmail")
        if not ticket or ticket.connection_id != connection.id:
            raise ValueError("Reply must target a ticket from the acting user's Gmail connection")
        if (
            arguments["to"].lower() != ticket.sender.lower()
            or arguments["thread_id"] != ticket.provider_thread_id
        ):
            raise ValueError("Reply recipient and thread must match the selected ticket")
        if normalized_subject(arguments["subject"]) != normalized_subject(ticket.subject):
            raise ValueError("Reply subject must match the selected ticket to preserve threading")
    elif kind == "slack_escalation":
        connection = actor_connection(db, run, "slack")
        workspace = db.get(Workspace, run.workspace_id)
        if not workspace.slack_channel or arguments["channel"] != workspace.slack_channel:
            raise ValueError("Escalations must target the owner-configured Slack channel")
    else:
        if not ticket or ticket.payment_id != arguments["payment_id"]:
            raise ValueError("An owner must explicitly link this payment to the ticket first")
    return arguments, connection, ticket


def create_action(db, run, kind, arguments, citations, rationale):
    arguments, connection, ticket = validate_proposal(db, run, kind, arguments)
    from app.config import settings

    if connection and not settings().demo_mode:
        provider = Composio()
        provider.account(connection)
        connection.account_email = provider.display_identity(connection)
    previous = latest_action(db, run)
    account_id, account_label = acting_account(db, run, connection)
    action = Action(
        workspace_id=run.workspace_id,
        run_id=run.id,
        kind=kind,
        connection_id=connection.id if connection else None,
        arguments=arguments,
        provider_account_id=account_id,
        acting_account_label=account_label,
        payload_hash=payload_hash(arguments),
        citations=citations,
        rationale=rationale[:2000],
        version=(previous.version + 1) if previous else 1,
        ticket_updated_at=ticket.updated_at if ticket else None,
        expires_at=now() + 86400,
    )
    db.add(action)
    db.flush()
    run.status = "awaiting_approval"
    db.flush()
    return action


def revalidate(db, run, action):
    if action.status != "approved" or action.expires_at < now():
        raise ReapprovalRequired("Approval is missing or expired")
    if payload_hash(action.arguments) != action.payload_hash:
        raise ReapprovalRequired("Approved payload changed")
    member = db.scalar(
        select(Membership).where(
            Membership.workspace_id == run.workspace_id, Membership.user_id == run.user_id
        )
    )
    approver = db.scalar(
        select(Membership).where(
            Membership.workspace_id == run.workspace_id,
            Membership.user_id == action.decided_by,
            Membership.role == "owner",
        )
    )
    if not member or not approver:
        raise ReapprovalRequired("Originating user or approver is no longer authorized")
    args, connection, ticket = validate_proposal(db, run, action.kind, action.arguments)
    if action.connection_id != (connection.id if connection else None):
        raise ReapprovalRequired("Acting connection changed")
    if action.provider_account_id != acting_account(db, run, connection)[0]:
        raise ReapprovalRequired("Acting provider account changed; a fresh draft and approval are required")
    if ticket and action.ticket_updated_at != ticket.updated_at:
        raise ReapprovalRequired("Ticket changed after this action was prepared")
    for citation in action.citations:
        document = tenant_get(db, Document, citation["document_id"], run.workspace_id)
        if document.deleted_at or document.version != citation["version"] or document.status != "ready":
            raise ReapprovalRequired("Cited documentation was removed or changed")
    from app.config import settings

    if not settings().demo_mode:
        provider = Composio()
        if connection:
            provider.account(connection)
        if action.kind == "gmail_reply":
            remote = provider.gmail_thread_version(connection, args["thread_id"])
            local = list(
                db.scalars(
                    select(Message.provider_message_id)
                    .where(
                        Message.workspace_id == run.workspace_id,
                        Message.ticket_id == ticket.id,
                        Message.direction == "inbound",
                    )
                    .order_by(Message.created_at.desc())
                )
            )
            # Historical messages predating activation need not be imported. Every known
            # inbound message must still exist, and the latest inbound must be the one reviewed.
            if not local or not remote or not set(local).issubset(remote) or remote[-1] != local[0]:
                raise ReapprovalRequired("Gmail thread has changed; sync and review a fresh draft")
        if action.kind == "stripe_refund":
            payment = Stripe(db.get(Workspace, run.workspace_id)).payment(args["payment_id"])
            if payment["currency"] != args["currency"] or payment["remaining"] < args["amount"]:
                raise ReapprovalRequired("Payment refundability changed")
    return args, connection, ticket


def execute_action(db, run, action):
    from app.config import settings

    existing = db.scalar(
        select(ToolExecution).where(
            ToolExecution.action_id == action.id, ToolExecution.workspace_id == run.workspace_id
        )
    )
    if existing and existing.status == "succeeded":
        return existing.output
    if existing and action.kind == "stripe_refund" and existing.status in {"dispatching", "retryable"}:
        if now() - existing.created_at > 23 * 3600:
            existing.status, action.status, run.status = "uncertain", "uncertain", "needs_attention"
            db.commit()
            raise ProviderError(
                "Stripe idempotency window nearly expired; owner reconciliation required", uncertain=True
            )
        if not settings().demo_mode:
            stripe = Stripe(db.get(Workspace, run.workspace_id))
            confirmed = stripe.find_refund(action.arguments["payment_id"], existing.idempotency_key)
            if confirmed:
                existing.status, existing.output, action.status = "succeeded", redact(confirmed), "executed"
                db.commit()
                return existing.output
        existing.status, action.status = "retryable", "approved"
        db.commit()
    if existing and existing.status in {"dispatching", "uncertain"}:
        run.status = "needs_attention"
        action.status = "uncertain"
        existing.status = "uncertain"
        db.commit()
        raise ProviderError(
            "Previous dispatch outcome is unknown; owner reconciliation required", uncertain=True
        )
    args, connection, ticket = revalidate(db, run, action)
    execution = existing or ToolExecution(
        workspace_id=run.workspace_id,
        action_id=action.id,
        idempotency_key=f"action:{action.id}:{action.version}",
    )
    if not existing:
        db.add(execution)
    claimed = db.execute(
        update(Action).where(Action.id == action.id, Action.status == "approved").values(status="executing")
    ).rowcount
    if not claimed:
        raise ReapprovalRequired("Action already consumed")
    execution.status = "dispatching"
    db.commit()  # Persist intent before crossing the external side-effect boundary.
    try:
        if settings().demo_mode:
            output = {"demo": True, "id": "demo_" + action.id[:8], "message": "Simulated action completed"}
        elif action.kind == "gmail_reply":
            output = Composio().send_reply(connection, args, action.id)
        elif action.kind == "slack_escalation":
            output = Composio().slack_send(connection, args, action.id)
        else:
            output = Stripe(db.get(Workspace, run.workspace_id)).refund(args, execution.idempotency_key)
        execution.status, execution.output = "succeeded", redact(output)
        action.status = "executed"
        if ticket:
            ticket.status = "escalated" if action.kind == "slack_escalation" else "resolved"
            ticket.updated_at = now()
        db.commit()
        TOOLS.labels(action.kind, "succeeded").inc()
        emit(db, run, "execute", "completed", {"kind": action.kind, "output": execution.output})
        return execution.output
    except ProviderError as exc:
        # A known refusal may be retried. Unknown non-idempotent outcomes may not.
        uncertain = exc.uncertain and action.kind != "stripe_refund"
        execution.status = "uncertain" if uncertain else "retryable" if exc.transient else "failed"
        execution.error = str(redact(str(exc)))
        action.status = "uncertain" if uncertain else "approved" if exc.transient else "failed"
        if uncertain:
            run.status = "needs_attention"
        db.commit()
        TOOLS.labels(action.kind, execution.status).inc()
        raise
    except Exception as exc:
        execution.status, action.status, run.status = "uncertain", "uncertain", "needs_attention"
        execution.error = str(redact(str(exc)))
        db.commit()
        raise ProviderError(
            "Unexpected failure after dispatch; reconcile before retry", uncertain=True
        ) from exc


def record_decision(db, who, action, decision, version, arguments=None):
    # CAS prevents two owners or duplicate HTTP requests from deciding the same version.
    if decision == "edit":
        if arguments is None:
            raise ValueError("Edited arguments are required")
        # Validate before any write or nested commit; an invalid edit cannot consume approval.
        run_for_validation = tenant_get(db, Run, action.run_id, who.workspace_id)
        validate_proposal(db, run_for_validation, action.kind, arguments)
    if action.version != version or action.status != "pending":
        raise ValueError("Action changed or was already decided; reload before continuing")
    if action.expires_at < now() and decision != "reject":
        raise ValueError("Approval expired; request a fresh draft")
    claimed = db.execute(
        update(Action)
        .where(Action.id == action.id, Action.version == version, Action.status == "pending")
        .values(status="deciding")
    ).rowcount
    if not claimed:
        raise ValueError("Another owner already decided this action")
    run = tenant_get(db, Run, action.run_id, who.workspace_id)
    if decision == "edit":
        if arguments is None:
            raise ValueError("Edited arguments are required")
        action.status = "superseded"
        replacement = create_action(db, run, action.kind, arguments, action.citations, action.rationale)
    else:
        action.status = "approved" if decision == "approve" else "rejected"
        action.decided_by, action.decided_at = who.user.id, now()
        replacement = action
    db.add(
        Audit(
            workspace_id=who.workspace_id,
            user_id=who.user.id,
            event="approval." + decision,
            entity_id=action.id,
            data={"version": version, "replacement_id": replacement.id},
        )
    )
    db.flush()
    return run, replacement
