from sqlalchemy import select

from app.models import Connection, Document
from app.security import decrypt, encrypt, redact
from conftest import sign_in


def test_csrf_and_workspace_isolation(env, client):
    client.headers.pop("X-CSRF-Token")
    assert (
        client.post(
            "/api/v1/runs", json={"prompt": "hello"}, headers={"Idempotency-Key": "csrf-test"}
        ).status_code
        == 403
    )
    sign_in(client)
    client.headers["X-Workspace-ID"] = env["other"]
    assert client.get("/api/v1/tickets").status_code == 403
    client.headers["X-Workspace-ID"] = env["workspace"]
    assert client.delete("/api/v1/connections/" + env["private"]).status_code == 404
    assert "private-secret" not in client.get("/api/v1/connections").text


def test_agent_cannot_approve_or_store_keys(env):
    client = env["client"]
    sign_in(client, "agent@example.com")
    assert client.post("/api/v1/workspace/stripe-key", json={"key": "sk_test_example"}).status_code == 403
    assert client.post("/api/v1/members/invites", json={"email": "new@example.com"}).status_code == 403
    assert client.get("/api/v1/connections").json()["items"] == []


def test_credentials_encrypted_and_redacted(env):
    value = "sk_test_supersecret"
    cipher = encrypt(value)
    assert value not in cipher
    assert decrypt(cipher) == value
    assert redact({"nested": {"access_token": "raw-secret"}, "message": "Bearer abc.def.xyz"}) == {
        "nested": {"access_token": "[redacted]"},
        "message": "[redacted]",
    }


def test_password_invite_replay_and_session_revocation(env, client):
    invite = (
        client.post("/api/v1/members/invites", json={"email": "new@example.com"})
        .json()["url"]
        .split("token=")[1]
    )
    result = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite, "name": "New", "password": "a-new-secure-password"},
    )
    assert result.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/accept-invite",
            json={"token": invite, "name": "New", "password": "a-new-secure-password"},
        ).status_code
        == 400
    )
    sign_in(client)
    members = client.get("/api/v1/members").json()["items"]
    member = next(m for m in members if m["email"] == "owner@example.com")
    link = client.post(f"/api/v1/members/{member['id']}/reset-link").json()["url"].split("token=")[1]
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": link, "password": "an-even-better-password"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/reset-password", json={"token": link, "password": "an-even-better-password"}
        ).status_code
        == 400
    )


def test_login_throttled_without_user_enumeration(env):
    client = env["client"]
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "missing@example.com", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "missing@example.com", "password": "wrong"}
        ).status_code
        == 429
    )


def test_origin_and_live_keys_rejected(env, client):
    assert client.post("/api/v1/workspace/stripe-key", json={"key": "sk_live_forbidden"}).status_code == 422
    assert (
        client.post(
            "/api/v1/members/invites",
            json={"email": "new@example.com"},
            headers={"Origin": "https://attacker.invalid"},
        ).status_code
        == 403
    )


def test_revocation_closes_local_gate_before_remote_failure(env, client, monkeypatch):
    from app.services.providers import Composio, ProviderError
    from app.config import settings

    monkeypatch.setattr(settings(), "demo_mode", False)
    monkeypatch.setattr(
        Composio, "request", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("unavailable"))
    )
    assert client.delete("/api/v1/connections/" + env["gmail"]).status_code == 503
    with env["factory"]() as db:
        connection = db.get(Connection, env["gmail"])
        assert connection.status == "disconnected" and not connection.automation_enabled


def test_removed_document_source_is_inaccessible(env, client):
    response = client.post(
        "/api/v1/documents", files={"file": ("guide.md", b"Helpful product knowledge.", "text/markdown")}
    )
    assert response.status_code == 202
    doc_id = response.json()["id"]
    assert client.delete("/api/v1/documents/" + doc_id).status_code == 200
    assert client.get("/api/v1/documents/" + doc_id + "/source").status_code == 404
    with env["factory"]() as db:
        assert db.scalar(select(Document).where(Document.id == doc_id)).deleted_at is not None


def test_cross_workspace_runs_approvals_events_and_sources(env, client):
    from test_workflow import prepare
    from app.models import Action

    run_id, action_id = prepare(env, client)
    with env["factory"]() as db:
        doc_id = db.get(Action, action_id).citations[0]["document_id"]
    sign_in(client, "other@example.com")
    for route in [
        f"/runs/{run_id}",
        f"/runs/{run_id}/events",
        f"/runs/{run_id}/events/stream",
        f"/tickets/{env['ticket']}",
        f"/documents/{doc_id}/source?version=1",
    ]:
        assert client.get("/api/v1" + route).status_code == 404, route
    assert (
        client.post(
            f"/api/v1/approvals/{action_id}/decide", json={"decision": "approve", "version": 1}
        ).status_code
        == 404
    )
    assert not client.get("/api/v1/approvals").json()["items"]
    assert not client.get("/api/v1/runs").json()["items"]


def test_removing_member_disables_originating_automation(env, client):
    from app.models import Membership

    with env["factory"]() as db:
        connection = Connection(
            workspace_id=env["workspace"],
            user_id=env["agent"],
            provider="gmail",
            account_id="agent-gmail",
            automation_enabled=True,
        )
        db.add(connection)
        member = db.scalar(
            select(Membership).where(
                Membership.workspace_id == env["workspace"], Membership.user_id == env["agent"]
            )
        )
        member_id = member.id
        db.commit()
        connection_id = connection.id
    assert client.delete(f"/api/v1/members/{member_id}").status_code == 200
    with env["factory"]() as db:
        assert not db.get(Connection, connection_id).automation_enabled


def test_session_is_committed_before_cookie_headers_are_sent(env):
    import asyncio
    import httpx
    from app.main import app
    from app.models import AuthSession

    observed = []

    async def probe(scope, receive, send):
        async def inspect_response(message):
            if message["type"] == "http.response.start":
                with env["factory"]() as db:
                    observed.append(bool(db.scalar(select(AuthSession.id))))
            await send(message)

        await app(scope, receive, inspect_response)

    async def login():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=probe), base_url="http://testserver"
        ) as http:
            response = await http.post(
                "/api/v1/auth/login",
                json={"email": "owner@example.com", "password": "correct-horse-password"},
            )
            assert response.status_code == 200

    asyncio.run(login())
    assert observed == [True]


def test_login_options_do_not_offer_unconfigured_or_production_demo_auth(env, monkeypatch):
    from app.config import settings

    config = settings()
    monkeypatch.setattr(config, "google_client_id", "")
    monkeypatch.setattr(config, "google_client_secret", "")
    assert env["client"].get("/api/v1/auth/options").json() == {"google_enabled": False, "demo_enabled": True}
    monkeypatch.setattr(config, "app_env", "production")
    assert not env["client"].get("/api/v1/auth/options").json()["demo_enabled"]
