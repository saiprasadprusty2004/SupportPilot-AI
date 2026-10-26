import hashlib
import logging
import random
from contextlib import contextmanager

from celery import Celery
from sqlalchemy import func, or_, select, text, update

from app.config import settings
from app.db import session_scope
from app.models import (
    Action,
    Connection,
    Document,
    Job,
    JobAttempt,
    Membership,
    Message,
    Outbox,
    Run,
    Ticket,
    ToolExecution,
    now,
    uid,
)
from app.security import payload_hash, redact
from app.services.events import ERRORS, RETRIES, emit
from app.services.providers import Composio, ProviderError, gmail_body, gmail_headers

logger = logging.getLogger(__name__)
celery = Celery("supportpilot", broker=settings().redis_url)
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 1800},
)
QUEUES = {
    "run": "agent",
    "resume": "outbound",
    "index": "ingestion",
    "sync": "ingestion",
    "backfill": "ingestion",
    "drive": "ingestion",
}


def enqueue(db, workspace_id, kind, entity_id, payload=None):
    job = Job(workspace_id=workspace_id, kind=kind, entity_id=entity_id, payload=payload or {})
    db.add(job)
    db.flush()
    db.add(Outbox(workspace_id=workspace_id, job_id=job.id))
    return job


def create_run(db, workspace_id, user_id, prompt, ticket_id, key):
    fingerprint = payload_hash({"prompt": prompt, "ticket_id": ticket_id, "user_id": user_id})
    existing = db.scalar(select(Run).where(Run.workspace_id == workspace_id, Run.idempotency_key == key))
    if existing:
        if existing.input_hash != fingerprint:
            raise ValueError("Idempotency key was already used with a different request")
        return existing
    run = Run(
        workspace_id=workspace_id,
        user_id=user_id,
        prompt=prompt,
        ticket_id=ticket_id,
        idempotency_key=key,
        input_hash=fingerprint,
    )
    db.add(run)
    db.flush()
    enqueue(db, workspace_id, "run", run.id)
    return run


@contextmanager
def advisory_lock(db, identifier):
    if db.bind.dialect.name != "postgresql":
        yield True
        return
    key = int(hashlib.sha256(identifier.encode()).hexdigest()[:15], 16)
    with db.bind.connect() as conn:
        locked = conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        try:
            yield locked
        finally:
            if locked:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


@contextmanager
def checkpointer():
    if settings().demo_mode and settings().database_url.startswith("sqlite"):
        from langgraph.checkpoint.sqlite import SqliteSaver

        with SqliteSaver.from_conn_string("data/checkpoints.db") as saver:
            yield saver
    else:
        from langgraph.checkpoint.postgres import PostgresSaver

        connection_string = (settings().worker_database_url or settings().database_url).replace(
            "postgresql+psycopg://", "postgresql://"
        )
        # Checkpoint tables are provisioned once by the migration command, not in each job.
        with PostgresSaver.from_conn_string(connection_string) as saver:
            yield saver


def sync_gmail(db, connection, backfill=False):
    if not connection.automation_enabled or connection.status != "active":
        return
    if not db.scalar(
        select(Membership.id).where(
            Membership.workspace_id == connection.workspace_id, Membership.user_id == connection.user_id
        )
    ):
        return
    provider = Composio()
    provider.account(connection)
    profile = provider.gmail_profile(connection)
    connection.account_email = profile.get("emailAddress", connection.account_email)
    if connection.sync_cursor is None and not backfill:
        connection.sync_started_at = now()
        connection.sync_cursor = str(connection.sync_started_at)
        connection.synced_at = now()
        return
    start = now()
    after = (
        float(connection.sync_cursor) - 120 if connection.sync_cursor and not backfill else now() - 7 * 86400
    )
    incoming = []
    for item in provider.gmail_messages(connection, after=after):
        if db.scalar(
            select(Message.id).where(
                Message.workspace_id == connection.workspace_id,
                Message.connection_id == connection.id,
                Message.provider_message_id == item["id"],
            )
        ):
            continue
        remote = provider.gmail_message(connection, item["id"])
        incoming.append(remote)
    # Gmail lists newest first. Apply messages chronologically so an older message
    # cannot overwrite the ticket preview or become the apparent latest customer message.
    for remote in sorted(incoming, key=lambda message: int(message.get("internalDate", "0"))):
        if (
            not backfill
            and connection.sync_started_at
            and int(remote.get("internalDate", "0")) / 1000 < connection.sync_started_at
        ):
            continue
        if any(label in remote.get("labelIds", []) for label in ("SENT", "DRAFT", "TRASH", "SPAM")):
            continue
        headers = gmail_headers(remote.get("payload", {}))
        sender = headers["sender_email"]
        if not sender or sender.lower() == connection.account_email.lower():
            continue
        body = gmail_body(remote.get("payload", {})) or remote.get("snippet", "")
        thread_id = remote["threadId"]
        ticket = db.scalar(
            select(Ticket).where(
                Ticket.workspace_id == connection.workspace_id,
                Ticket.connection_id == connection.id,
                Ticket.provider_thread_id == thread_id,
            )
        )
        if not ticket:
            ticket = Ticket(
                workspace_id=connection.workspace_id,
                connection_id=connection.id,
                provider_thread_id=thread_id,
                subject=headers.get("subject", "Untitled ticket")[:500],
                sender=sender,
                preview=body[:500],
            )
            db.add(ticket)
            db.flush()
        ticket.status, ticket.preview, ticket.updated_at = "open", body[:500], now()
        db.add(
            Message(
                workspace_id=connection.workspace_id,
                ticket_id=ticket.id,
                connection_id=connection.id,
                provider_message_id=remote["id"],
                sender=sender,
                body=body,
                created_at=int(remote.get("internalDate", "0")) / 1000,
            )
        )
        create_run(
            db,
            connection.workspace_id,
            connection.user_id,
            "Read the incoming ticket, retrieve relevant documentation, and prepare a helpful reply.",
            ticket.id,
            "gmail:" + connection.id + ":" + remote["id"],
        )
    connection.sync_cursor, connection.synced_at = str(start), now()


def perform(db, job):
    from app.services.knowledge import index_document
    from app.services.workflow import run_workflow

    if job.kind == "index":
        doc = db.get(Document, job.entity_id)
        if doc and doc.workspace_id == job.workspace_id:
            with advisory_lock(db, "document:" + doc.id) as locked:
                if not locked:
                    raise ProviderError("Document indexing already running", transient=True, retry_after=5)
                index_document(db, doc)
    elif job.kind in {"sync", "backfill"}:
        connection = db.get(Connection, job.entity_id)
        if connection and connection.workspace_id == job.workspace_id:
            with advisory_lock(db, "sync:" + connection.id) as locked:
                if not locked:
                    raise ProviderError("Mailbox sync already running", transient=True, retry_after=5)
                sync_gmail(db, connection, backfill=job.kind == "backfill")
    elif job.kind in {"run", "resume"}:
        run = db.get(Run, job.entity_id)
        if not run or run.workspace_id != job.workspace_id or run.status in {"completed", "rejected"}:
            return
        identifier = "thread:" + run.ticket_id if run.ticket_id else "run:" + run.id
        with advisory_lock(db, identifier) as locked:
            if not locked:
                raise ProviderError("Another run is using this ticket", transient=True, retry_after=5)
            with checkpointer() as saver:
                run_workflow(db, run, saver, resume=job.kind == "resume")
    else:
        raise ValueError("Unknown job kind")


def process_job(job_id, workspace_id):
    lease = uid()
    with session_scope(workspace_id, worker=True) as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(78465132)"))
        job = db.scalar(
            select(Job).where(Job.id == job_id, Job.workspace_id == workspace_id).with_for_update()
        )
        if not job or job.status not in {"pending", "queued", "retrying"} or job.available_at > now():
            return
        running = db.scalar(
            select(func.count()).select_from(Job).where(Job.status == "running", Job.lease_until > now())
        )
        workspace_running = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.workspace_id == workspace_id, Job.status == "running", Job.lease_until > now())
        )
        if running >= settings().global_concurrency or workspace_running >= settings().workspace_concurrency:
            job.status, job.available_at = "pending", now() + 3
            return
        job.status, job.lease_owner, job.lease_until = "running", lease, now() + 900
        job.attempts += 1
        number = (db.scalar(select(func.max(JobAttempt.number)).where(JobAttempt.job_id == job.id)) or 0) + 1
        attempt = JobAttempt(workspace_id=workspace_id, job_id=job.id, number=number, lease_owner=lease)
        db.add(attempt)
        db.commit()
        try:
            perform(db, job)
            job.status, job.lease_until = "completed", None
            job.last_error = None
            attempt.status, attempt.finished_at = "completed", now()
            db.commit()
        except Exception as exc:
            db.rollback()
            db.refresh(job)
            run = db.get(Run, job.entity_id) if job.kind in {"run", "resume"} else None
            message = str(redact(str(exc)))[:2000]
            job.last_error, job.lease_until = message, None
            quota = isinstance(exc, ProviderError) and exc.quota
            uncertain = isinstance(exc, ProviderError) and exc.uncertain
            transient = isinstance(exc, ProviderError) and exc.transient
            if quota:
                job.status = "waiting_quota"
                job.available_at = now() + max(exc.retry_after, 60)
                if run:
                    run.status = "waiting_quota"
            elif transient and job.attempts < 5 and not uncertain:
                delay = max(getattr(exc, "retry_after", 0), min(300, 2**job.attempts + random.random() * 3))
                job.status, job.available_at = "retrying", now() + delay
                RETRIES.labels(job.kind).inc()
                if run:
                    run.status = "retrying"
            else:
                job.status = "needs_attention" if uncertain else "dead_letter"
                if run:
                    run.status = "needs_attention" if uncertain else "failed"
            attempt.status, attempt.finished_at, attempt.error = job.status, now(), message
            if run:
                run.error = message
                emit(
                    db,
                    run,
                    "worker",
                    job.status,
                    {"error": message, "attempt": job.attempts, "retry_at": job.available_at},
                )
            ERRORS.labels(job.kind).inc()
            db.commit()
            logger.warning("job_failed", extra={"job_id": job.id, "kind": job.kind, "state": job.status})


@celery.task(name="supportpilot.execute", soft_time_limit=780, time_limit=840)
def execute_job(job_id, workspace_id):
    process_job(job_id, workspace_id)


def dispatch_once(demo=False):
    with session_scope(worker=True) as db:
        current = now()
        # Recover broker loss, worker death, and quota parks from durable records.
        expired = list(
            db.scalars(
                select(Job)
                .where(Job.status == "running", Job.lease_until < current)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        for stale in expired:
            error = "Worker lease expired before completion"
            db.execute(
                update(JobAttempt)
                .where(JobAttempt.job_id == stale.id, JobAttempt.status == "running")
                .values(status="abandoned", finished_at=current, error=error)
            )
            run = db.get(Run, stale.entity_id) if stale.kind in {"run", "resume"} else None
            ambiguous = (
                db.execute(
                    select(Action, ToolExecution)
                    .join(ToolExecution, ToolExecution.action_id == Action.id)
                    .where(
                        Action.run_id == stale.entity_id,
                        Action.workspace_id == stale.workspace_id,
                        Action.kind != "stripe_refund",
                        ToolExecution.status == "dispatching",
                    )
                ).first()
                if run
                else None
            )
            if ambiguous:
                action, execution = ambiguous
                action.status, execution.status, stale.status = "uncertain", "uncertain", "needs_attention"
                run.status, run.error = "needs_attention", error + "; reconcile the provider outcome"
            elif stale.attempts >= 5:
                stale.status = "dead_letter"
                if run:
                    run.status, run.error = "failed", error + "; automatic recovery budget exhausted"
                elif stale.kind == "index":
                    document = db.get(Document, stale.entity_id)
                    if document and document.workspace_id == stale.workspace_id:
                        document.status, document.error = (
                            "failed",
                            error + "; retry indexing after inspecting the file",
                        )
            else:
                stale.status = "pending"
            stale.lease_owner, stale.lease_until, stale.available_at, stale.last_error = (
                None,
                None,
                current,
                error,
            )
        db.execute(
            update(Job)
            .where(Job.status == "queued", Job.available_at < current - 120)
            .values(status="pending", available_at=current)
        )
        db.execute(
            update(Job)
            .where(Job.status == "waiting_quota", Job.available_at <= current)
            .values(status="pending", attempts=0)
        )
        jobs = list(
            db.scalars(
                select(Job)
                .where(Job.status.in_(["pending", "retrying"]), Job.available_at <= current)
                .order_by(Job.available_at)
                .limit(50)
            )
        )
        for job in jobs:
            job.status = "queued"
            db.commit()
            if demo:
                process_job(job.id, job.workspace_id)
            else:
                try:
                    execute_job.apply_async(args=[job.id, job.workspace_id], queue=QUEUES[job.kind])
                    outbox = db.scalar(select(Outbox).where(Outbox.job_id == job.id))
                    if outbox:
                        outbox.published_at = now()
                    db.commit()
                except Exception:
                    job.status = "pending"
                    db.commit()
                    logger.warning("broker_unavailable")
                    break


def schedule_mailboxes():
    if settings().demo_mode:
        return
    with session_scope(worker=True) as db:
        connections = list(
            db.scalars(
                select(Connection).where(
                    Connection.provider == "gmail",
                    Connection.automation_enabled.is_(True),
                    Connection.status == "active",
                    or_(Connection.synced_at.is_(None), Connection.synced_at < now() - 60),
                )
            )
        )
        for connection in connections:
            pending = db.scalar(
                select(Job.id).where(
                    Job.entity_id == connection.id,
                    Job.kind.in_(["sync", "backfill"]),
                    Job.status.in_(["pending", "queued", "running", "retrying"]),
                )
            )
            if not pending:
                enqueue(db, connection.workspace_id, "sync", connection.id)
