from sqlalchemy import select

from app.models import Action, Job, Run, RunEvent, Ticket, ToolExecution, now
from app.services.jobs import process_job


def prepare(env, client, prompt="Draft a reply to this team invitation ticket"):
    response = client.post(
        "/api/v1/documents",
        files={
            "file": (
                "guide.md",
                b"Team invitations: owners invite teammates from Settings Members. Check the spam folder. Invitations expire after 48 hours. Share the invite link directly if email is not delivered.",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 202, response.text
    with env["factory"]() as db:
        job = db.scalar(select(Job).where(Job.entity_id == response.json()["id"]))
        job_id = job.id
    process_job(job_id, env["workspace"])
    response = client.post(
        "/api/v1/runs",
        json={"prompt": prompt, "ticket_id": env["ticket"]},
        headers={"Idempotency-Key": "workflow-test-key"},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    with env["factory"]() as db:
        job = db.scalar(select(Job).where(Job.entity_id == run_id))
        job_id = job.id
    process_job(job_id, env["workspace"])
    with env["factory"]() as db:
        action = db.scalar(select(Action).where(Action.run_id == run_id).order_by(Action.version.desc()))
        run = db.get(Run, run_id)
        assert run.status == "awaiting_approval", run.error
        return run_id, action.id


def resume_jobs(env, run_id):
    with env["factory"]() as db:
        ids = list(db.scalars(select(Job.id).where(Job.entity_id == run_id, Job.kind == "resume")))
    for identifier in ids:
        process_job(identifier, env["workspace"])


def test_durable_approval_edit_resume_and_no_duplicate_send(env, client):
    run_id, action_id = prepare(env, client)
    action = next(a for a in client.get("/api/v1/approvals").json()["items"] if a["id"] == action_id)
    args = {
        **action["arguments"],
        "body": "Hi! Please check your spam folder or ask the owner to share a fresh invitation link.",
    }
    edited = client.post(
        f"/api/v1/approvals/{action_id}/decide", json={"decision": "edit", "version": 1, "arguments": args}
    )
    assert edited.status_code == 200, edited.text
    replacement = edited.json()
    assert replacement["version"] == 2 and replacement["status"] == "pending"
    assert (
        client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/approvals/{replacement['id']}/decide", json={"decision": "approve", "version": 2}
        ).status_code
        == 200
    )
    resume_jobs(env, run_id)
    with env["factory"]() as db:
        run = db.get(Run, run_id)
        assert run.status == "completed", run.error
        executions = list(
            db.scalars(select(ToolExecution).where(ToolExecution.action_id == replacement["id"]))
        )
        assert len(executions) == 1 and executions[0].status == "succeeded"
        sequence = list(
            db.scalars(select(RunEvent.sequence).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence))
        )
        assert sequence == list(range(1, len(sequence) + 1))
    resume_jobs(env, run_id)
    with env["factory"]() as db:
        assert len(list(db.scalars(select(ToolExecution)))) == 1


def test_rejection_never_dispatches(env, client):
    run_id, action_id = prepare(env, client)
    assert (
        client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "reject", "version": 1}
        ).status_code
        == 200
    )
    resume_jobs(env, run_id)
    assert client.get("/api/v1/runs/" + run_id).json()["status"] == "rejected"
    with env["factory"]() as db:
        assert not db.scalar(select(ToolExecution.id))


def test_stale_ticket_requires_fresh_approval(env, client):
    run_id, action_id = prepare(env, client)
    client.post(f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1})
    with env["factory"]() as db:
        db.get(Ticket, env["ticket"]).updated_at = now() + 10
        db.commit()
    resume_jobs(env, run_id)
    with env["factory"]() as db:
        actions = list(db.scalars(select(Action).where(Action.run_id == run_id).order_by(Action.version)))
        assert len(actions) == 2 and actions[-1].status == "pending"
        assert not db.scalar(select(ToolExecution.id))


def test_changed_provider_account_requires_fresh_approval(env, client):
    from app.models import Connection

    run_id, action_id = prepare(env, client)
    client.post(f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1})
    with env["factory"]() as db:
        connection = db.get(Connection, env["gmail"])
        connection.account_id = "a-different-connected-account"
        connection.account_email = "new-mailbox@example.com"
        db.commit()
    resume_jobs(env, run_id)
    with env["factory"]() as db:
        actions = list(db.scalars(select(Action).where(Action.run_id == run_id).order_by(Action.version)))
        assert len(actions) == 2 and actions[0].status == "superseded"
        assert actions[1].status == "pending"
        assert actions[1].acting_account_label == "new-mailbox@example.com"
        assert not db.scalar(select(ToolExecution.id))


def test_deleted_source_retrieves_fresh_evidence_before_reapproval(env, client):
    run_id, action_id = prepare(env, client)
    with env["factory"]() as db:
        original_doc = db.get(Action, action_id).citations[0]["document_id"]
    client.post(f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1})
    client.delete("/api/v1/documents/" + original_doc)
    new_doc = client.post(
        "/api/v1/documents",
        files={
            "file": (
                "updated-guide.md",
                b"Team invitations: owners now invite teammates from the Workspace Directory. This is the updated product procedure.",
                "text/markdown",
            )
        },
    ).json()["id"]
    with env["factory"]() as db:
        job_id = db.scalar(select(Job.id).where(Job.entity_id == new_doc))
    process_job(job_id, env["workspace"])
    resume_jobs(env, run_id)
    with env["factory"]() as db:
        replacement = db.scalar(select(Action).where(Action.run_id == run_id).order_by(Action.version.desc()))
        assert replacement.status == "pending" and replacement.version == 2
        assert replacement.citations[0]["document_id"] == new_doc
        assert "Workspace Directory" in replacement.arguments["body"]
        assert not db.scalar(select(ToolExecution.id))


def test_concurrent_owner_decisions_consume_one_version(env, client):
    from concurrent.futures import ThreadPoolExecutor

    run_id, action_id = prepare(env, client)

    def decide():
        return client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: decide(), range(2))) == [200, 409]
    with env["factory"]() as db:
        assert len(list(db.scalars(select(Job).where(Job.entity_id == run_id, Job.kind == "resume")))) == 1


def test_expiry_payload_target_and_duplicate_decision(env, client):
    run_id, action_id = prepare(env, client)
    with env["factory"]() as db:
        db.get(Action, action_id).expires_at = now() - 1
        db.commit()
    assert (
        client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "reject", "version": 1}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "reject", "version": 1}
        ).status_code
        == 409
    )


def test_idempotency_conflict_and_replay(env, client):
    headers = {"Idempotency-Key": "same-request-key"}
    first = client.post("/api/v1/runs", json={"prompt": "Summarize product documentation"}, headers=headers)
    replay = client.post("/api/v1/runs", json={"prompt": "Summarize product documentation"}, headers=headers)
    assert first.json()["id"] == replay.json()["id"]
    assert client.post("/api/v1/runs", json={"prompt": "Different task"}, headers=headers).status_code == 409


def test_refund_and_slack_still_need_approval(env, client):
    run_id, action_id = prepare(env, client, "Escalate this support ticket")
    with env["factory"]() as db:
        assert db.get(Action, action_id).kind == "slack_escalation"
        assert not db.scalar(select(ToolExecution.id))
    assert (
        client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1}
        ).status_code
        == 200
    )
    resume_jobs(env, run_id)
    assert client.get("/api/v1/runs/" + run_id).json()["status"] == "completed"


def test_gmail_intake_baseline_order_dedup_and_outbound_filter(env, monkeypatch):
    import base64
    from unittest.mock import Mock
    from app.models import Connection, Message
    from app.services.jobs import sync_gmail
    from app.services.providers import Composio

    monkeypatch.setattr(Composio, "account", Mock())
    monkeypatch.setattr(Composio, "gmail_profile", Mock(return_value={"emailAddress": "support@example.com"}))
    listing = Mock(return_value=[])
    monkeypatch.setattr(Composio, "gmail_messages", listing)
    with env["factory"]() as db:
        connection = db.get(Connection, env["gmail"])
        sync_gmail(db, connection)
        db.commit()
        assert connection.sync_cursor and not listing.called
        start = connection.sync_started_at

        def message(identifier, offset, sent=False):
            return {
                "id": identifier,
                "threadId": "intake-thread",
                "internalDate": str(int((start + offset) * 1000)),
                "labelIds": ["SENT" if sent else "INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "Customer <customer@example.com>"},
                        {"name": "Subject", "value": "Invitation support"},
                    ],
                    "body": {"data": base64.urlsafe_b64encode(identifier.encode()).decode()},
                },
            }

        remote = {
            "old": message("old", -10),
            "newer": message("newer", 2),
            "earlier": message("earlier", 1),
            "outbound": message("outbound", 3, True),
        }
        listing.return_value = [{"id": identifier} for identifier in ["newer", "old", "earlier", "outbound"]]
        monkeypatch.setattr(
            Composio, "gmail_message", lambda self, connection, identifier: remote[identifier]
        )
        sync_gmail(db, connection)
        db.commit()
        sync_gmail(db, connection)
        db.commit()
        ticket = db.scalar(select(Ticket).where(Ticket.provider_thread_id == "intake-thread"))
        assert ticket.preview == "newer"
        messages = list(
            db.scalars(select(Message).where(Message.ticket_id == ticket.id).order_by(Message.created_at))
        )
        assert [m.provider_message_id for m in messages] == ["earlier", "newer"]
        assert len(list(db.scalars(select(Run).where(Run.ticket_id == ticket.id)))) == 2
