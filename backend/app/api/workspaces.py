from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Connection, Membership, OneTimeToken, User, Workspace, now
from app.schemas import InviteInput, StripeKeyInput, WorkspaceUpdate
from app.security import Identity, audit, database, digest, encrypt, identity, owner, token

router = APIRouter(tags=["workspaces"])


@router.get("/workspace")
def workspace(
    who: Identity = Depends(identity, scope="function"), db: Session = Depends(database, scope="function")
):
    item = db.get(Workspace, who.workspace_id)
    return {
        "id": item.id,
        "name": item.name,
        "slack_channel": item.slack_channel,
        "stripe_configured": bool(item.stripe_key_ciphertext),
    }


@router.patch("/workspace")
def update_workspace(
    body: WorkspaceUpdate,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    item = db.get(Workspace, who.workspace_id)
    item.name, item.slack_channel = body.name, body.slack_channel
    audit(db, who, "workspace.updated", item.id)
    return {"ok": True}


@router.post("/workspace/stripe-key")
def stripe_key(
    body: StripeKeyInput,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    item = db.get(Workspace, who.workspace_id)
    item.stripe_key_ciphertext = encrypt(body.key)
    audit(db, who, "workspace.stripe_key_updated", item.id)
    return {"ok": True}


@router.get("/members")
def members(
    who: Identity = Depends(identity, scope="function"), db: Session = Depends(database, scope="function")
):
    rows = db.execute(
        select(User, Membership)
        .join(Membership, User.id == Membership.user_id)
        .where(Membership.workspace_id == who.workspace_id)
    ).all()
    return {
        "items": [
            {"id": m.id, "user_id": u.id, "email": u.email, "name": u.name, "role": m.role} for u, m in rows
        ],
        "next_cursor": None,
    }


@router.post("/members/invites")
def invite(
    body: InviteInput,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    raw = token()
    db.add(
        OneTimeToken(
            token_hash=digest(raw),
            kind="invite",
            email=str(body.email).lower(),
            workspace_id=who.workspace_id,
            role=body.role,
            expires_at=now() + 48 * 3600,
        )
    )
    audit(db, who, "member.invited", str(body.email))
    return {"url": settings().app_url + "/invite?token=" + raw, "expires_in": 48 * 3600}


@router.post("/members/{membership_id}/reset-link")
def reset_link(
    membership_id: str,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    member = db.scalar(
        select(Membership).where(Membership.id == membership_id, Membership.workspace_id == who.workspace_id)
    )
    if not member:
        raise HTTPException(404, "Member not found")
    user, raw = db.get(User, member.user_id), token()
    if member.user_id != who.user.id:
        memberships = list(db.scalars(select(Membership).where(Membership.user_id == member.user_id)))
        if len(memberships) != 1:
            raise HTTPException(403, "An owner cannot reset an account shared with other workspaces")
    db.add(
        OneTimeToken(
            token_hash=digest(raw),
            kind="reset",
            email=user.email,
            workspace_id=who.workspace_id,
            role="self" if member.user_id == who.user.id else "workspace",
            expires_at=now() + 1800,
        )
    )
    audit(db, who, "member.reset_requested", user.id)
    return {"url": settings().app_url + "/reset?token=" + raw}


@router.delete("/members/{membership_id}")
def remove_member(
    membership_id: str,
    who: Identity = Depends(owner, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    member = db.scalar(
        select(Membership).where(Membership.id == membership_id, Membership.workspace_id == who.workspace_id)
    )
    if not member:
        raise HTTPException(404, "Member not found")
    if member.user_id == who.user.id:
        raise HTTPException(400, "An owner cannot remove their own membership")
    db.execute(delete(Membership).where(Membership.id == member.id))
    db.execute(
        update(Connection)
        .where(Connection.workspace_id == who.workspace_id, Connection.user_id == member.user_id)
        .values(automation_enabled=False)
    )
    audit(db, who, "member.removed", member.user_id)
    return {"ok": True}
