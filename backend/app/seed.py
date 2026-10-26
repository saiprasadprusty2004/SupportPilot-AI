from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db import session_scope, set_scope
from app.models import Connection, Document, Membership, Message, Run, Ticket, User, Workspace, now, uid
from app.security import digest
from app.services.jobs import create_run
from app.services.knowledge import index_document
from app.services.storage import storage


def seed_demo():
    if not settings().demo_mode:
        raise RuntimeError("Demo seeding is disabled in live mode")
    with session_scope(worker=True) as db:
        if db.scalar(select(User.id).where(User.email == "alex@acme.studio")):
            return
        user = User(email="alex@acme.studio", name="Alex Morgan")
        workspace = Workspace(name="Acme Studio", slack_channel="support-engineering")
        db.add_all([user, workspace])
        db.flush()
        set_scope(db, workspace.id)
        db.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
        connections = {}
        for provider, address in [
            ("gmail", "support@acme.studio"),
            ("slack", "Acme Studio"),
            ("googledrive", "alex@acme.studio"),
        ]:
            connection = Connection(
                workspace_id=workspace.id,
                user_id=user.id,
                provider=provider,
                account_id="demo-" + provider,
                account_email=address,
                automation_enabled=True,
                scopes=["demo"],
            )
            db.add(connection)
            db.flush()
            connections[provider] = connection
        db.commit()
        root = Path(__file__).resolve().parents[2]
        for name in ("product-handbook.md", "billing-policy.md", "getting-started.md"):
            content = (root / "samples" / name).read_bytes()
            identifier = uid()
            key = f"{workspace.id}/{identifier}/v1"
            storage().put(key, content)
            document = Document(
                id=identifier,
                workspace_id=workspace.id,
                uploaded_by=user.id,
                name=name,
                storage_key=key,
                mime_type="text/markdown",
                size=len(content),
                content_hash=digest(content.decode()),
            )
            db.add(document)
            db.commit()
            index_document(db, document)
        samples = [
            (
                "Trouble inviting my team",
                "sarah.chen@velvet.design",
                "Hi! I just upgraded to the Team plan, but my teammates are not receiving their invitations. Could you help us get set up?",
                "open",
                "high",
            ),
            (
                "Question about our latest invoice",
                "james@orbit.io",
                "Could you help me understand the additional seats on our October invoice? Thank you!",
                "open",
                "normal",
            ),
            (
                "How do I export my project?",
                "mia@formandfield.co",
                "We would love to export our project as a PDF for our client presentation. What is the best way to do that?",
                "resolved",
                "normal",
            ),
            (
                "API rate limit on our integration",
                "daniel@layer.dev",
                "We have been seeing 429 responses since this morning. Could your engineering team take a look?",
                "escalated",
                "high",
            ),
        ]
        for i, (subject, sender, body, status, priority) in enumerate(samples):
            ticket = Ticket(
                workspace_id=workspace.id,
                connection_id=connections["gmail"].id,
                provider_thread_id=f"demo-thread-{i}",
                subject=subject,
                sender=sender,
                preview=body,
                status=status,
                priority=priority,
                created_at=now() - (i + 1) * 300,
                updated_at=now() - (i + 1) * 300,
                payment_id="pi_demo_invoice" if i == 1 else None,
            )
            db.add(ticket)
            db.flush()
            db.add(
                Message(
                    workspace_id=workspace.id,
                    ticket_id=ticket.id,
                    connection_id=connections["gmail"].id,
                    provider_message_id=f"demo-message-{i}",
                    sender=sender,
                    body=body,
                    created_at=ticket.created_at,
                )
            )
            if i < 2:
                create_run(
                    db,
                    workspace.id,
                    user.id,
                    "Read this ticket and prepare a helpful, cited reply.",
                    ticket.id,
                    f"seed-ticket-{i}",
                )
            else:
                db.add(
                    Run(
                        workspace_id=workspace.id,
                        user_id=user.id,
                        ticket_id=ticket.id,
                        prompt="Help Mia export her project"
                        if i == 2
                        else "Escalate integration rate-limit issue",
                        status="completed",
                        current_node="summarize",
                        result="Illustrative demo history; no external action was performed.",
                        idempotency_key=f"seed-history-{i}",
                        input_hash=digest(subject),
                        created_at=now() - i * 900,
                        completed_at=now() - i * 800,
                    )
                )
