import os

os.environ["DEMO_MODE"] = "true"
os.environ["SUPPORTPILOT_TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///./data/test-bootstrap.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import db as database_module
from app import security
from app.config import settings
from app.db import Base, make_engine
from app.main import app
from app.models import Connection, Membership, Message, Ticket, User, Workspace


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = make_engine("sqlite:///" + str(tmp_path / "test.db"))
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    monkeypatch.setattr(database_module, "_worker_factory", None)
    monkeypatch.setattr(security, "SessionLocal", factory)
    monkeypatch.setattr(settings(), "database_url", "sqlite:///" + str(tmp_path / "test.db"))
    monkeypatch.setattr(settings(), "worker_database_url", "")
    monkeypatch.setattr(settings(), "storage_path", str(tmp_path / "uploads"))
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings(), "encryption_key", Fernet.generate_key().decode())
    Base.metadata.create_all(engine)
    with factory() as db:
        workspace = Workspace(name="Tenant A", slack_channel="C_SUPPORT")
        other = Workspace(name="Tenant B")
        user = User(
            email="owner@example.com",
            name="Owner",
            password_hash=security.passwords.hash("correct-horse-password"),
        )
        agent = User(
            email="agent@example.com",
            name="Agent",
            password_hash=security.passwords.hash("correct-horse-password"),
        )
        outsider = User(
            email="other@example.com",
            name="Other",
            password_hash=security.passwords.hash("correct-horse-password"),
        )
        db.add_all([workspace, other, user, agent, outsider])
        db.flush()
        db.add_all(
            [
                Membership(workspace_id=workspace.id, user_id=user.id, role="owner"),
                Membership(workspace_id=workspace.id, user_id=agent.id, role="agent"),
                Membership(workspace_id=other.id, user_id=outsider.id, role="owner"),
            ]
        )
        gmail = Connection(
            workspace_id=workspace.id,
            user_id=user.id,
            provider="gmail",
            account_id="demo-gmail",
            account_email="support@example.com",
            automation_enabled=True,
        )
        slack = Connection(
            workspace_id=workspace.id,
            user_id=user.id,
            provider="slack",
            account_id="demo-slack",
            automation_enabled=True,
        )
        private = Connection(
            workspace_id=other.id, user_id=outsider.id, provider="gmail", account_id="private-secret"
        )
        db.add_all([gmail, slack, private])
        db.flush()
        ticket = Ticket(
            workspace_id=workspace.id,
            connection_id=gmail.id,
            provider_thread_id="thread-1",
            subject="Team invitations missing",
            sender="customer@example.com",
            preview="How do I invite my teammates?",
            payment_id="pi_test123",
        )
        db.add(ticket)
        db.flush()
        db.add(
            Message(
                workspace_id=workspace.id,
                ticket_id=ticket.id,
                connection_id=gmail.id,
                provider_message_id="msg-1",
                sender=ticket.sender,
                body=ticket.preview,
            )
        )
        db.commit()
        values = {
            "workspace": workspace.id,
            "other": other.id,
            "user": user.id,
            "agent": agent.id,
            "outsider": outsider.id,
            "ticket": ticket.id,
            "gmail": gmail.id,
            "private": private.id,
        }
    from contextlib import contextmanager
    from langgraph.checkpoint.sqlite import SqliteSaver

    @contextmanager
    def saver():
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as value:
            yield value

    from app.services import jobs

    monkeypatch.setattr(jobs, "checkpointer", saver)
    with TestClient(app) as client:
        yield {**values, "factory": factory, "client": client, "saver": saver, "tmp": tmp_path}
    engine.dispose()


def sign_in(client, email="owner@example.com"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-password"})
    assert response.status_code == 200, response.text
    response = client.get("/api/v1/auth/me")
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    client.headers["X-Workspace-ID"] = response.json()["workspaces"][0]["id"]
    return response.json()


@pytest.fixture
def client(env):
    sign_in(env["client"])
    return env["client"]
