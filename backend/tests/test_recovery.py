from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Action, Job, JobAttempt, Run, ToolExecution, now
from app.services.approvals import execute_action, revalidate
from app.services.jobs import dispatch_once, enqueue, process_job
from app.services.providers import Composio, ProviderError, Stripe
from test_workflow import prepare


def test_exponential_retry_and_dead_letter(env, monkeypatch):
    from app.services import jobs

    with env["factory"]() as db:
        job = enqueue(db, env["workspace"], "sync", env["gmail"])
        db.commit()
        identifier = job.id
    monkeypatch.setattr(jobs, "perform", Mock(side_effect=ProviderError("temporary", transient=True)))
    for attempt in range(1, 6):
        process_job(identifier, env["workspace"])
        with env["factory"]() as db:
            job = db.get(Job, identifier)
            assert job.attempts == attempt
            assert job.status == ("retrying" if attempt < 5 else "dead_letter")
            if attempt < 5:
                assert now() < job.available_at <= now() + 301
                job.available_at = now() - 1
                db.commit()
    with env["factory"]() as db:
        history = list(
            db.scalars(select(JobAttempt).where(JobAttempt.job_id == identifier).order_by(JobAttempt.number))
        )
        assert [a.number for a in history] == [1, 2, 3, 4, 5]
        assert all(a.finished_at and a.error == "temporary" for a in history)
        assert history[-1].status == "dead_letter"


def test_quota_parks_instead_of_hot_loop(env, monkeypatch):
    from app.services import jobs

    with env["factory"]() as db:
        job = enqueue(db, env["workspace"], "sync", env["gmail"])
        db.commit()
        identifier = job.id
    monkeypatch.setattr(
        jobs, "perform", Mock(side_effect=ProviderError("quota", quota=True, retry_after=3600))
    )
    process_job(identifier, env["workspace"])
    with env["factory"]() as db:
        job = db.get(Job, identifier)
        assert job.status == "waiting_quota"
        assert job.available_at > now() + 3500


def test_broker_outage_preserves_durable_job(env, monkeypatch):
    from app.services import jobs

    with env["factory"]() as db:
        job = enqueue(db, env["workspace"], "sync", env["gmail"])
        db.commit()
        identifier = job.id
    monkeypatch.setattr(jobs.execute_job, "apply_async", Mock(side_effect=ConnectionError("Redis down")))
    dispatch_once(demo=False)
    with env["factory"]() as db:
        assert db.get(Job, identifier).status == "pending"


def test_worker_death_recovers_expired_lease(env, monkeypatch):
    from app.services import jobs

    with env["factory"]() as db:
        job = enqueue(db, env["workspace"], "sync", env["gmail"])
        job.status, job.lease_until = "running", now() - 1
        db.flush()
        db.add(JobAttempt(workspace_id=env["workspace"], job_id=job.id, number=1, lease_owner="dead-worker"))
        db.commit()
        identifier = job.id
    monkeypatch.setattr(jobs, "perform", Mock())
    dispatch_once(demo=True)
    with env["factory"]() as db:
        assert db.get(Job, identifier).status == "completed"
        attempts = list(
            db.scalars(select(JobAttempt).where(JobAttempt.job_id == identifier).order_by(JobAttempt.number))
        )
        assert [attempt.status for attempt in attempts] == ["abandoned", "completed"]


def test_repeated_worker_death_exhausts_recovery_budget(env, monkeypatch):
    from app.services import jobs

    with env["factory"]() as db:
        job = enqueue(db, env["workspace"], "sync", env["gmail"])
        job.status, job.lease_until, job.attempts = "running", now() - 1, 5
        db.commit()
        identifier = job.id
    perform = Mock()
    monkeypatch.setattr(jobs, "perform", perform)
    dispatch_once(demo=True)
    with env["factory"]() as db:
        assert db.get(Job, identifier).status == "dead_letter"
    perform.assert_not_called()


def test_worker_loss_during_send_requires_reconciliation(env, client, monkeypatch):
    from app.services import jobs

    run_id, action_id = prepare(env, client)
    assert (
        client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1}
        ).status_code
        == 200
    )
    with env["factory"]() as db:
        job = db.scalar(select(Job).where(Job.entity_id == run_id, Job.kind == "resume"))
        job.status, job.lease_until, job.attempts = "running", now() - 1, 1
        db.get(Action, action_id).status = "executing"
        db.add(
            ToolExecution(
                workspace_id=env["workspace"],
                action_id=action_id,
                idempotency_key="lost-worker-send",
                status="dispatching",
            )
        )
        db.commit()
        job_id = job.id
    perform = Mock()
    monkeypatch.setattr(jobs, "perform", perform)
    dispatch_once(demo=True)
    with env["factory"]() as db:
        assert db.get(Job, job_id).status == "needs_attention"
        assert db.get(Action, action_id).status == "uncertain"
        assert db.get(Run, run_id).status == "needs_attention"
    perform.assert_not_called()


def test_unknown_email_outcome_cannot_be_blindly_retried(env, client, monkeypatch):
    run_id, action_id = prepare(env, client)
    client.post(f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1})
    with env["factory"]() as db:
        action = db.get(Action, action_id)
        db.add(
            ToolExecution(
                workspace_id=env["workspace"],
                action_id=action.id,
                idempotency_key="uncertain-send",
                status="dispatching",
            )
        )
        db.commit()
        with pytest.raises(ProviderError, match="unknown"):
            execute_action(db, db.get(Run, run_id), action)
        assert action.status == "uncertain"
    assert client.post("/api/v1/runs/" + run_id + "/retry", json={}).status_code == 409
    assert (
        client.post(
            "/api/v1/approvals/" + action_id + "/reconcile",
            json={
                "outcome": "confirmed_not_sent",
                "evidence": "Owner inspected sent mailbox and confirmed no matching message.",
            },
        ).status_code
        == 200
    )
    with env["factory"]() as db:
        replacement = db.scalar(select(Action).where(Action.run_id == run_id).order_by(Action.version.desc()))
        assert replacement.status == "pending" and replacement.version == 2


def test_payload_tampering_blocked(env, client):
    run_id, action_id = prepare(env, client)
    client.post(f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1})
    with env["factory"]() as db:
        action = db.get(Action, action_id)
        action.arguments = {**action.arguments, "body": "Tampered"}
        db.commit()
        from app.services.approvals import ReapprovalRequired

        with pytest.raises(ReapprovalRequired, match="payload"):
            revalidate(db, db.get(Run, run_id), action)


def test_composio_checks_identity_toolkit_and_auth_config(env, monkeypatch):
    from app.models import Connection

    monkeypatch.setattr(settings(), "composio_gmail_auth_config", "auth_minimal")
    with env["factory"]() as db:
        connection = db.get(Connection, env["gmail"])
        result = {
            "user_id": env["other"] + ":" + env["user"],
            "status": "ACTIVE",
            "toolkit": {"slug": "gmail"},
            "auth_config": {"id": "auth_minimal"},
        }
        provider = Composio()
        monkeypatch.setattr(provider, "request", lambda *a, **kw: result)
        with pytest.raises(ProviderError, match="identity"):
            provider.account(connection)
        result["user_id"] = env["workspace"] + ":" + env["user"]
        assert provider.account(connection) == result
        result["toolkit"]["slug"] = "slack"
        with pytest.raises(ProviderError, match="toolkit"):
            provider.account(connection)


def test_stripe_refund_uses_stable_key_and_rejects_changed_balance(env):
    stripe = object.__new__(Stripe)
    stripe.payment = Mock(return_value={"remaining": 5000, "currency": "usd"})
    stripe.request = Mock(return_value={"id": "re_test", "livemode": False})
    args = {"payment_id": "pi_test", "amount": 4900, "currency": "usd", "reason": "requested_by_customer"}
    stripe.refund(args, "stable-approved-key")
    assert stripe.request.call_args.kwargs["key"] == "stable-approved-key"
    assert stripe.request.call_args.kwargs["data"]["metadata[supportpilot_action]"] == "stable-approved-key"
    stripe.payment.return_value["remaining"] = 100
    with pytest.raises(ProviderError, match="remaining"):
        stripe.refund(args, "stable-approved-key")
