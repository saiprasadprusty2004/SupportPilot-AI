from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.dto import ConnectionOut, PageOut
from app.models import Connection, Membership, OAuthAttempt, now
from app.schemas import ConnectInput, ConnectionUpdate
from app.security import Identity, audit, authenticated, database, digest, identity, tenant_get, token
from app.serialization import public
from app.services.jobs import enqueue
from app.services.providers import SCOPES, Composio

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("", response_model=PageOut[ConnectionOut])
def connections(
    who: Identity = Depends(identity, scope="function"), db: Session = Depends(database, scope="function")
):
    items = db.scalars(
        select(Connection).where(
            Connection.workspace_id == who.workspace_id, Connection.user_id == who.user.id
        )
    )
    return {"items": [public(item, exclude=["account_id"]) for item in items], "next_cursor": None}


@router.post("/connect")
def connect(
    body: ConnectInput,
    response: Response,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    state = token()
    attempt = OAuthAttempt(
        user_id=who.user.id,
        workspace_id=who.workspace_id,
        state_hash=digest(state),
        nonce=token(),
        provider=body.provider,
        expires_at=now() + 600,
    )
    db.add(attempt)
    result = Composio().connect(
        f"{who.workspace_id}:{who.user.id}",
        body.provider,
        settings().app_url + "/api/v1/connections/callback",
    )
    attempt.data = {"account_id": result["connected_account_id"]}
    response.set_cookie(
        "sp_connect",
        state,
        httponly=True,
        secure=settings().app_env == "production",
        samesite="lax",
        max_age=600,
        path="/api/v1/connections",
    )
    audit(db, who, "connection.started", body.provider)
    return {"redirect_url": result["redirect_url"]}


@router.get("/callback")
def callback(
    request: Request,
    session_uri: str,
    auth=Depends(authenticated, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    # The configured Composio verifier redeems using authenticated identity, never callback user IDs.
    user, auth_session = auth
    attempt = db.scalar(
        select(OAuthAttempt).where(
            OAuthAttempt.user_id == user.id,
            OAuthAttempt.state_hash == digest(request.cookies.get("sp_connect", "")),
            OAuthAttempt.expires_at > now(),
        )
    )
    if not attempt:
        raise HTTPException(400, "Connection attempt expired or browser state mismatch")
    member = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.workspace_id == attempt.workspace_id
        )
    )
    if not member:
        raise HTTPException(403, "Workspace access revoked")
    from app.db import set_scope

    set_scope(db, member.workspace_id)
    who = Identity(user, member, auth_session)
    result = Composio().complete(f"{who.workspace_id}:{who.user.id}", session_uri)
    provider = result["toolkit_slug"]
    if provider not in SCOPES:
        raise HTTPException(400, "Unexpected connection provider")
    if attempt.provider != provider or attempt.data.get("account_id") != result["connected_account_id"]:
        raise HTTPException(400, "No matching connection attempt")
    connection = db.scalar(
        select(Connection).where(
            Connection.workspace_id == who.workspace_id,
            Connection.user_id == who.user.id,
            Connection.provider == provider,
        )
    )
    if not connection:
        connection = Connection(
            workspace_id=who.workspace_id,
            user_id=who.user.id,
            provider=provider,
            account_id=result["connected_account_id"],
        )
        db.add(connection)
    connection.account_id, connection.status = result["connected_account_id"], "active"
    connection.account_email = ""
    connection.scopes, connection.automation_enabled, connection.sync_cursor = SCOPES[provider], False, None
    Composio().account(connection)
    db.delete(attempt)
    audit(db, who, "connection.completed", provider)
    response = RedirectResponse(settings().app_url + "/connections?connected=" + provider)
    response.delete_cookie("sp_connect", path="/api/v1/connections")
    return response


def owned(db, connection_id, who):
    connection = tenant_get(db, Connection, connection_id, who.workspace_id)
    if connection.user_id != who.user.id:
        raise HTTPException(404, "Connection not found")
    return connection


@router.patch("/{connection_id}")
def configure(
    connection_id: str,
    body: ConnectionUpdate,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    connection = owned(db, connection_id, who)
    if body.automation_enabled and not body.approval_policy_accepted:
        raise HTTPException(400, "Explicit approval-policy consent is required")
    if connection.label != body.label or (body.automation_enabled and not connection.automation_enabled):
        connection.sync_cursor = None
        connection.sync_started_at = None
    connection.automation_enabled, connection.label = body.automation_enabled, body.label
    audit(
        db,
        who,
        "connection.automation_updated",
        connection.id,
        {
            "automation_enabled": body.automation_enabled,
            "owner_approval_policy_accepted": body.approval_policy_accepted,
        },
    )
    return public(connection, exclude=["account_id"])


@router.delete("/{connection_id}")
def disconnect(
    connection_id: str,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    connection = owned(db, connection_id, who)
    # Stop local dispatch before contacting the provider; revocation failures leave the local gate closed.
    connection.status, connection.automation_enabled = "disconnected", False
    audit(db, who, "connection.disconnected", connection.id)
    db.commit()
    if not settings().demo_mode:
        Composio().request("POST", "/connected_accounts/" + connection.account_id + "/revoke")
    return {"ok": True}


@router.post("/{connection_id}/backfill")
def backfill(
    connection_id: str,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    connection = owned(db, connection_id, who)
    if connection.provider != "gmail" or not connection.automation_enabled:
        raise HTTPException(400, "Enable Gmail automation before requesting a 7-day backfill")
    job = enqueue(db, who.workspace_id, "backfill", connection.id)
    audit(db, who, "connection.backfill", connection.id)
    return {"job_id": job.id}


@router.get("/{connection_id}/channels")
def channels(
    connection_id: str,
    who: Identity = Depends(identity, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    connection = owned(db, connection_id, who)
    if connection.provider != "slack":
        raise HTTPException(400, "Not a Slack connection")
    if connection.status != "active":
        raise HTTPException(409, "Reconnect Slack before discovering channels")
    Composio().account(connection)
    return {"items": Composio().slack_channels(connection)}
