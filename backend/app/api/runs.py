import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import session_scope
from app.dto import ActionOut, EventOut, PageOut, RunOut, TicketOut
from app.models import Action, Audit, Job, JobAttempt, Message, Run, RunEvent, Ticket, ToolExecution, now
from app.schemas import ApprovalDecision, PaymentLink, ReconcileInput, RunInput
from app.security import Identity, audit, database, identity, owner, tenant_get
from app.serialization import page, public
from app.services.approvals import latest_action, record_decision
from app.services.jobs import create_run, enqueue

router = APIRouter(tags=["execution"])


@router.get("/tickets", response_model=PageOut[TicketOut])
def tickets(
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    rows, next_cursor = page(db, Ticket, who.workspace_id, limit, cursor)
    return {"items": [public(t) for t in rows], "next_cursor": next_cursor}


@router.get("/tickets/{ticket_id}")
def ticket(
    ticket_id: str,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    item = tenant_get(db, Ticket, ticket_id, who.workspace_id)
    messages = db.scalars(
        select(Message)
        .where(Message.workspace_id == who.workspace_id, Message.ticket_id == item.id)
        .order_by(Message.created_at)
        .limit(100)
    )
    return {**public(item), "messages": [public(m) for m in messages]}


@router.post("/tickets/{ticket_id}/payment")
def link_payment(
    ticket_id: str,
    body: PaymentLink,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    item = tenant_get(db, Ticket, ticket_id, who.workspace_id)
    from app.config import settings
    from app.models import Workspace
    from app.services.providers import Stripe

    if not settings().demo_mode:
        Stripe(db.get(Workspace, who.workspace_id)).payment(body.payment_id)
    item.payment_id, item.updated_at = body.payment_id, now()
    audit(db, who, "ticket.payment_linked", item.id, {"payment_id": body.payment_id})
    return {"ok": True}


@router.get("/runs", response_model=PageOut[RunOut])
def runs(
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    rows, next_cursor = page(db, Run, who.workspace_id, limit, cursor)
    return {
        "items": [public(r, exclude=["input_hash", "idempotency_key"]) for r in rows],
        "next_cursor": next_cursor,
    }


@router.post("/runs", status_code=202, response_model=RunOut)
def start(
    body: RunInput,
    idempotency_key: str = Header(min_length=8, max_length=100),
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    if body.ticket_id:
        tenant_get(db, Ticket, body.ticket_id, who.workspace_id)
    try:
        run = create_run(db, who.workspace_id, who.user.id, body.prompt, body.ticket_id, idempotency_key)
        db.commit()
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except IntegrityError:
        db.rollback()
        run = create_run(db, who.workspace_id, who.user.id, body.prompt, body.ticket_id, idempotency_key)
    return public(run, exclude=["input_hash", "idempotency_key"])


@router.get("/runs/{run_id}", response_model=RunOut)
def run(
    run_id: str,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    return public(tenant_get(db, Run, run_id, who.workspace_id), exclude=["input_hash", "idempotency_key"])


@router.get("/runs/{run_id}/events", response_model=PageOut[EventOut])
def events(
    run_id: str,
    after: int = Query(0, ge=0),
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    tenant_get(db, Run, run_id, who.workspace_id)
    rows = list(
        db.scalars(
            select(RunEvent)
            .where(
                RunEvent.run_id == run_id,
                RunEvent.workspace_id == who.workspace_id,
                RunEvent.sequence > after,
            )
            .order_by(RunEvent.sequence)
            .limit(200)
        )
    )
    return {
        "items": [public(row) for row in rows],
        "next_cursor": str(rows[-1].sequence) if len(rows) == 200 else None,
    }


@router.get("/runs/{run_id}/jobs")
def run_jobs(
    run_id: str,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    tenant_get(db, Run, run_id, who.workspace_id)
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.workspace_id == who.workspace_id, Job.entity_id == run_id)
            .order_by(Job.created_at.desc())
            .limit(30)
        )
    )
    return {
        "items": [
            {
                **public(job),
                "history": [
                    public(attempt)
                    for attempt in db.scalars(
                        select(JobAttempt)
                        .where(JobAttempt.workspace_id == who.workspace_id, JobAttempt.job_id == job.id)
                        .order_by(JobAttempt.number.desc())
                        .limit(50)
                    )
                ],
            }
            for job in jobs
        ]
    }


@router.get("/runs/{run_id}/events/stream")
def stream(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    last_event_id: str | None = Header(None),
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    tenant_get(db, Run, run_id, who.workspace_id)
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError:
        raise HTTPException(400, "Invalid event cursor")
    workspace_id, user_id, auth_id = who.workspace_id, who.user.id, who.session.id

    def read_events(position):
        from app.models import AuthSession, Membership

        with session_scope(workspace_id) as session:
            authorized = session.get(AuthSession, auth_id)
            member = session.scalar(
                select(Membership.id).where(
                    Membership.workspace_id == workspace_id, Membership.user_id == user_id
                )
            )
            if not authorized or authorized.expires_at < now() or not member:
                return None
            return [
                public(e)
                for e in session.scalars(
                    select(RunEvent)
                    .where(
                        RunEvent.run_id == run_id,
                        RunEvent.workspace_id == workspace_id,
                        RunEvent.sequence > position,
                    )
                    .order_by(RunEvent.sequence)
                    .limit(200)
                )
            ]

    async def generate():
        position = cursor
        deadline = now() + 300  # Bounded connection lifetime; EventSource reconnects with Last-Event-ID.
        while now() < deadline:
            if await request.is_disconnected():
                break
            rows = await asyncio.to_thread(read_events, position)
            if rows is None:
                yield "event: auth_expired\ndata: {}\n\n"
                return
            for row in rows:
                position = row["sequence"]
                yield f"id: {position}\nevent: trace\ndata: {json.dumps(row)}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
                await asyncio.sleep(2)

    # End the request's read transaction before holding an SSE connection open.
    db.commit()
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/approvals", response_model=PageOut[ActionOut])
def approvals(
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    rows, next_cursor = page(db, Action, who.workspace_id, limit, cursor)
    return {"items": [public(a) for a in rows], "next_cursor": next_cursor}


@router.post("/approvals/{action_id}/decide", response_model=ActionOut)
def decide(
    action_id: str,
    body: ApprovalDecision,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    action = tenant_get(db, Action, action_id, who.workspace_id)
    try:
        run, replacement = record_decision(db, who, action, body.decision, body.version, body.arguments)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if body.decision != "edit":
        enqueue(db, who.workspace_id, "resume", run.id)
    return public(replacement)


@router.post("/approvals/{action_id}/reconcile")
def reconcile(
    action_id: str,
    body: ReconcileInput,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    action = tenant_get(db, Action, action_id, who.workspace_id)
    if action.status != "uncertain":
        raise HTTPException(409, "Only uncertain dispatches can be reconciled")
    claimed = db.execute(
        update(Action)
        .where(Action.id == action.id, Action.status == "uncertain")
        .values(status="reconciling")
    ).rowcount
    if not claimed:
        raise HTTPException(409, "Another owner already reconciled this action")
    execution = db.scalar(
        select(ToolExecution).where(
            ToolExecution.action_id == action.id, ToolExecution.workspace_id == who.workspace_id
        )
    )
    run = tenant_get(db, Run, action.run_id, who.workspace_id)
    if body.outcome == "confirmed_sent":
        action.status, execution.status = "executed", "succeeded"
        execution.output = {"reconciled": True, "provider_reference": body.provider_reference}
        run.status, run.result, run.completed_at = (
            "completed",
            "Owner verified the provider completed this action.",
            now(),
        )
    else:
        execution.status, action.status = "failed", "superseded"
        from app.services.approvals import create_action

        create_action(
            db,
            run,
            action.kind,
            action.arguments,
            action.citations,
            "Owner verified previous action was not performed. Fresh approval required.",
        )
    audit(db, who, "action.reconciled", action.id, body.model_dump())
    return {"ok": True}


@router.post("/approvals/{action_id}/renew", response_model=ActionOut)
def renew(
    action_id: str,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    action = tenant_get(db, Action, action_id, who.workspace_id)
    if action.status != "pending" or action.expires_at >= now():
        raise HTTPException(409, "Only an expired pending action may be renewed")
    claimed = db.execute(
        update(Action).where(Action.id == action.id, Action.status == "pending").values(status="superseded")
    ).rowcount
    if not claimed:
        raise HTTPException(409, "Action changed; reload before renewing")
    from app.services.approvals import create_action

    run = tenant_get(db, Run, action.run_id, who.workspace_id)
    replacement = create_action(
        db,
        run,
        action.kind,
        action.arguments,
        action.citations,
        "Previous approval window expired. Review this fresh version before approving.",
    )
    audit(db, who, "approval.renewed", replacement.id)
    return public(replacement)


@router.post("/runs/{run_id}/retry")
def retry(
    run_id: str,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    item = tenant_get(db, Run, run_id, who.workspace_id)
    if item.status not in {"failed", "waiting_quota", "retrying"}:
        raise HTTPException(
            409, "Only failed or quota-limited runs can be retried; uncertain outcomes require reconciliation"
        )
    action = latest_action(db, item)
    if action and action.status in {"uncertain", "executing"}:
        raise HTTPException(409, "Reconcile the prior action first")
    existing = db.scalar(
        select(Job)
        .where(
            Job.workspace_id == who.workspace_id,
            Job.entity_id == item.id,
            Job.status.in_(["dead_letter", "waiting_quota", "retrying"]),
        )
        .order_by(Job.created_at.desc())
    )
    if existing:
        existing.status, existing.attempts, existing.available_at = "pending", 0, now()
    else:
        enqueue(db, who.workspace_id, "resume" if action else "run", item.id)
    item.status, item.error = "queued", None
    audit(db, who, "run.retry", item.id)
    return {"ok": True}


@router.get("/dead-letters")
def dead_letters(
    who: Identity = Depends(owner, scope="function"), db: Session = Depends(database, scope="function")
):
    return {
        "items": [
            public(j)
            for j in db.scalars(
                select(Job)
                .where(
                    Job.workspace_id == who.workspace_id, Job.status.in_(["dead_letter", "needs_attention"])
                )
                .order_by(Job.created_at.desc())
                .limit(100)
            )
        ]
    }


@router.get("/audit")
def audits(
    who: Identity = Depends(owner, scope="function"), db: Session = Depends(database, scope="function")
):
    return {
        "items": [
            public(a)
            for a in db.scalars(
                select(Audit)
                .where(Audit.workspace_id == who.workspace_id)
                .order_by(Audit.created_at.desc())
                .limit(100)
            )
        ]
    }


@router.get("/dashboard")
def dashboard(
    who: Identity = Depends(identity, scope="function"), db: Session = Depends(database, scope="function")
):
    counts = {
        status: count
        for status, count in db.execute(
            select(Run.status, func.count()).where(Run.workspace_id == who.workspace_id).group_by(Run.status)
        )
    }
    tickets = db.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.workspace_id == who.workspace_id)
    )
    return {
        "tickets": tickets,
        "resolved_tickets": db.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.workspace_id == who.workspace_id, Ticket.status == "resolved")
        ),
        "runs": counts,
        "pending_approvals": db.scalar(
            select(func.count())
            .select_from(Action)
            .where(Action.workspace_id == who.workspace_id, Action.status == "pending")
        ),
    }
