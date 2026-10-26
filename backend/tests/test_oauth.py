from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

from sqlalchemy import select

from app.config import settings
from app.models import OAuthAttempt, User, now


def test_google_pkce_nonce_and_explicit_account_link(env, client, monkeypatch):
    from authlib.jose import JsonWebKey, jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import httpx

    monkeypatch.setattr(settings(), "google_client_id", "test-client")
    monkeypatch.setattr(settings(), "google_client_secret", "test-secret")
    response = client.get("/api/v1/auth/google/start?link=true", follow_redirects=False)
    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    state = query["state"][0]
    with env["factory"]() as db:
        attempt = db.scalar(select(OAuthAttempt))
        nonce = attempt.nonce
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    jwk = JsonWebKey.import_key(public, {"kid": "test-key"})
    encoded = jwt.encode(
        {"alg": "RS256", "kid": "test-key"},
        {
            "iss": "https://accounts.google.com",
            "sub": "google-owner-identity",
            "aud": "test-client",
            "exp": int(now() + 300),
            "iat": int(now()),
            "nonce": nonce,
            "email": "owner@example.com",
            "email_verified": True,
        },
        pem,
    ).decode()
    monkeypatch.setattr(
        httpx,
        "post",
        Mock(
            return_value=httpx.Response(
                200,
                json={"id_token": encoded},
                request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
            )
        ),
    )
    monkeypatch.setattr(
        httpx,
        "get",
        Mock(
            return_value=httpx.Response(
                200,
                json={"keys": [jwk.as_dict()]},
                request=httpx.Request("GET", "https://www.googleapis.com/oauth2/v3/certs"),
            )
        ),
    )
    bad = client.get(
        "/api/v1/auth/google/callback", params={"code": "test-code", "state": "wrong"}, follow_redirects=False
    )
    assert bad.status_code == 400
    response = client.get(
        "/api/v1/auth/google/callback", params={"code": "test-code", "state": state}, follow_redirects=False
    )
    assert response.status_code == 307, response.text
    with env["factory"]() as db:
        assert db.get(User, env["user"]).google_sub == "google-owner-identity"
        assert not db.scalar(select(OAuthAttempt))
    assert (
        client.get(
            "/api/v1/auth/google/callback",
            params={"code": "test-code", "state": state},
            follow_redirects=False,
        ).status_code
        == 400
    )


def test_composio_callback_requires_authenticated_browser_attempt(env, client):
    assert (
        client.get("/api/v1/connections/callback?session_uri=untrusted", follow_redirects=False).status_code
        == 400
    )


def test_composio_callback_binds_account_provider_identity_and_browser(env, client, monkeypatch):
    from app.services.providers import Composio

    monkeypatch.setattr(settings(), "composio_gmail_auth_config", "auth_gmail")
    monkeypatch.setattr(
        Composio,
        "connect",
        lambda *a: {
            "connected_account_id": "new-account",
            "redirect_url": "https://connect.composio.dev/fixture",
        },
    )
    complete = Mock(return_value={"connected_account_id": "different-account", "toolkit_slug": "gmail"})
    monkeypatch.setattr(Composio, "complete", complete)
    assert client.post("/api/v1/connections/connect", json={"provider": "gmail"}).status_code == 200
    assert (
        client.get("/api/v1/connections/callback?session_uri=fixture", follow_redirects=False).status_code
        == 400
    )
    complete.return_value["connected_account_id"] = "new-account"
    monkeypatch.setattr(
        Composio,
        "request",
        lambda *a, **kw: {
            "user_id": env["workspace"] + ":" + env["user"],
            "status": "ACTIVE",
            "toolkit": {"slug": "gmail"},
            "auth_config": {"id": "auth_gmail"},
        },
    )
    assert (
        client.get("/api/v1/connections/callback?session_uri=fixture", follow_redirects=False).status_code
        == 307
    )
    assert complete.call_args.args == (env["workspace"] + ":" + env["user"], "fixture")
    connections = client.get("/api/v1/connections").json()["items"]
    assert not next(c for c in connections if c["provider"] == "gmail")["automation_enabled"]
    assert (
        client.get("/api/v1/connections/callback?session_uri=fixture", follow_redirects=False).status_code
        == 400
    )


def test_invalid_approval_edit_does_not_consume_pending_action(env, client):
    from app.models import Action
    from test_workflow import prepare

    _, action_id = prepare(env, client)
    response = client.post(
        "/api/v1/approvals/" + action_id + "/decide",
        json={"decision": "edit", "version": 1, "arguments": {"to": "attacker@example.com"}},
    )
    assert response.status_code == 409
    with env["factory"]() as db:
        assert db.get(Action, action_id).status == "pending"
