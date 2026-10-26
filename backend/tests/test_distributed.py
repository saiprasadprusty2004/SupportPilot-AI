"""Real pgvector + Redis/Celery + PostgreSQL checkpoint round trip (CI or opt-in)."""

import os
import time
from contextlib import contextmanager
from uuid import uuid4

import pytest
from celery.contrib.testing.worker import start_worker
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import sessionmaker

from app import db as database_module, security
from app.config import settings
from app.db import Base
from app.models import AuthSession, Connection, Membership, Message, Ticket, User, Workspace
from app.services import jobs


@pytest.mark.postgres
def test_postgres_redis_worker_approval_round_trip(env, client, monkeypatch):
    app_url = os.getenv("POSTGRES_TEST_URL")
    worker_url = os.getenv("WORKER_DATABASE_URL")
    if not app_url or not worker_url:
        pytest.skip("Requires migrated PostgreSQL roles/checkpoints and Redis")
    app_engine, worker_engine = create_engine(app_url), create_engine(worker_url)
    app_factory = sessionmaker(app_engine, expire_on_commit=False)
    worker_factory = sessionmaker(worker_engine, expire_on_commit=False)
    workspaces = [env["workspace"], env["other"]]
    users = [env["user"], env["agent"], env["outsider"]]
    thread_ids = []
    try:
        # Clone only this test's unique records, including its already-authenticated cookie session.
        with env["factory"]() as source, worker_factory.begin() as target:
            for model in [User, Workspace, Membership, AuthSession, Connection, Ticket, Message]:
                for row in source.scalars(select(model)):
                    target.add(
                        model(**{column.key: getattr(row, column.key) for column in model.__table__.columns})
                    )
                target.flush()
        monkeypatch.setattr(database_module, "SessionLocal", app_factory)
        monkeypatch.setattr(database_module, "_worker_factory", worker_factory)
        monkeypatch.setattr(security, "SessionLocal", app_factory)
        monkeypatch.setattr(settings(), "database_url", app_url)
        monkeypatch.setattr(settings(), "worker_database_url", worker_url)

        @contextmanager
        def saver():
            with PostgresSaver.from_conn_string(
                worker_url.replace("postgresql+psycopg://", "postgresql://")
            ) as value:
                yield value

        monkeypatch.setattr(jobs, "checkpointer", saver)
        queue = "ci-" + uuid4().hex
        monkeypatch.setattr(jobs, "QUEUES", {kind: queue for kind in jobs.QUEUES})

        def await_value(read, expected):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                jobs.dispatch_once()
                if read() == expected:
                    return
                time.sleep(0.05)
            pytest.fail(f"Worker did not reach {expected!r}; last value: {read()!r}")

        with start_worker(
            jobs.celery,
            pool="threads",
            concurrency=2,
            queues=[queue],
            perform_ping_check=False,
            loglevel="WARNING",
        ):
            uploaded = client.post(
                "/api/v1/documents",
                files={
                    "file": (
                        "distributed.md",
                        b"Team invitations: owners invite teammates in Settings Members. Check spam for missing invitations.",
                        "text/markdown",
                    )
                },
            )
            assert uploaded.status_code == 202, uploaded.text
            document_id = uploaded.json()["id"]
            await_value(
                lambda: next(
                    d for d in client.get("/api/v1/documents").json()["items"] if d["id"] == document_id
                )["status"],
                "ready",
            )
            citations = client.post("/api/v1/search", json={"query": "team invitations"}).json()["items"]
            assert citations and citations[0]["document_id"] == document_id
            run = client.post(
                "/api/v1/runs",
                json={"prompt": "Prepare a cited invitation reply", "ticket_id": env["ticket"]},
                headers={"Idempotency-Key": "distributed-" + uuid4().hex},
            )
            assert run.status_code == 202, run.text
            run_id = run.json()["id"]
            thread_ids.append(run_id)

            def read_run():
                return client.get("/api/v1/runs/" + run_id).json()["status"]

            await_value(read_run, "awaiting_approval")
            action = next(a for a in client.get("/api/v1/approvals").json()["items"] if a["run_id"] == run_id)
            edited = client.post(
                f"/api/v1/approvals/{action['id']}/decide",
                json={
                    "decision": "edit",
                    "version": 1,
                    "arguments": {
                        **action["arguments"],
                        "body": "Reviewed: invite teammates from Settings Members.",
                    },
                },
            )
            assert edited.status_code == 200
            action = edited.json()
            assert (
                client.post(
                    f"/api/v1/approvals/{action['id']}/decide", json={"decision": "approve", "version": 2}
                ).status_code
                == 200
            )
            await_value(read_run, "completed")
            with saver() as checkpoint:
                assert checkpoint.get_tuple({"configurable": {"thread_id": run_id}})
            assert client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    finally:
        # Delete only IDs created by this test, never purge queues or shared tables.
        with worker_engine.begin() as db:
            if thread_ids:
                for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    for thread_id in thread_ids:
                        db.execute(text(f"DELETE FROM {table} WHERE thread_id=:id"), {"id": thread_id})
            for table in reversed(Base.metadata.sorted_tables):
                if "workspace_id" in table.c:
                    db.execute(delete(table).where(table.c.workspace_id.in_(workspaces)))
                elif "user_id" in table.c:
                    db.execute(delete(table).where(table.c.user_id.in_(users)))
                elif table.name == "users":
                    db.execute(delete(table).where(table.c.id.in_(users)))
                elif table.name == "workspaces":
                    db.execute(delete(table).where(table.c.id.in_(workspaces)))
        app_engine.dispose()
        worker_engine.dispose()
