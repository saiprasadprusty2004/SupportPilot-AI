import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.dto import SessionOut
from app.models import AuthSession, Membership, OAuthAttempt, OneTimeToken, User, Workspace, now
from app.schemas import AcceptInvite, LoginInput, ResetInput
from app.security import authenticated, check_password, database, digest, passwords, throttle, token

router = APIRouter(prefix="/auth", tags=["authentication"])
DUMMY_HASH = passwords.hash("constant-time-invalid-password")


def session_response(db, user, response):
    raw, csrf = token(), token()
    db.add(
        AuthSession(user_id=user.id, token_hash=digest(raw), csrf_token=csrf, expires_at=now() + 7 * 86400)
    )
    response.set_cookie(
        "sp_session",
        raw,
        httponly=True,
        secure=settings().app_env == "production",
        samesite="lax",
        max_age=7 * 86400,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/login")
def login(
    body: LoginInput, request: Request, response: Response, db: Session = Depends(database, scope="function")
):
    email = str(body.email).lower()
    throttle(db, "login:" + digest(email), 5)
    throttle(db, "login-ip:" + digest(request.client.host if request.client else "unknown"), 60)
    user = db.scalar(select(User).where(User.email == email))
    valid = check_password(user.password_hash if user and user.password_hash else DUMMY_HASH, body.password)
    if not user or not valid or not user.password_hash:
        raise HTTPException(401, "Email or password is incorrect")
    return session_response(db, user, response)


@router.post("/demo")
def demo(response: Response, db: Session = Depends(database, scope="function")):
    if not settings().demo_mode or settings().app_env == "production":
        raise HTTPException(404, "Not found")
    user = db.scalar(select(User).where(User.email == "alex@acme.studio"))
    if not user:
        raise HTTPException(503, "Seed the demo workspace first")
    return session_response(db, user, response)


@router.get("/options")
def login_options():
    config = settings()
    return {
        "google_enabled": bool(config.google_client_id and config.google_client_secret),
        "demo_enabled": config.demo_mode and config.app_env != "production",
    }


@router.get("/me", response_model=SessionOut)
def me(
    response: Response,
    auth=Depends(authenticated, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    user, record = auth
    rows = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return {
        "user": {"id": user.id, "name": user.name, "email": user.email},
        "workspaces": [{"id": w.id, "name": w.name, "role": role} for w, role in rows],
        "csrf_token": record.csrf_token,
        "demo_mode": settings().demo_mode,
    }


@router.post("/logout")
def logout(
    response: Response,
    auth=Depends(authenticated, scope="function"),
    db: Session = Depends(database, scope="function"),
):
    db.delete(auth[1])
    response.delete_cookie("sp_session", path="/")
    return {"ok": True}


def consume_token(db, raw, kind):
    record = db.scalar(
        select(OneTimeToken).where(
            OneTimeToken.token_hash == digest(raw),
            OneTimeToken.kind == kind,
            OneTimeToken.used_at.is_(None),
            OneTimeToken.expires_at > now(),
        )
    )
    if not record:
        raise HTTPException(400, "This link has expired or was already used")
    changed = db.execute(
        update(OneTimeToken)
        .where(OneTimeToken.id == record.id, OneTimeToken.used_at.is_(None))
        .values(used_at=now())
    ).rowcount
    if not changed:
        raise HTTPException(409, "Link already used")
    return record


@router.post("/accept-invite")
def accept_invite(body: AcceptInvite, response: Response, db: Session = Depends(database, scope="function")):
    invitation = consume_token(db, body.token, "invite")
    user = db.scalar(select(User).where(User.email == invitation.email))
    if user and not check_password(user.password_hash, body.password):
        raise HTTPException(
            409, "Account exists. Enter your current password or sign in with Google to accept."
        )
    if not user:
        user = User(email=invitation.email, name=body.name, password_hash=passwords.hash(body.password))
        db.add(user)
        db.flush()
    existing = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.workspace_id == invitation.workspace_id
        )
    )
    if not existing:
        db.add(Membership(user_id=user.id, workspace_id=invitation.workspace_id, role=invitation.role))
    return session_response(db, user, response)


@router.post("/reset-password")
def reset_password(body: ResetInput, db: Session = Depends(database, scope="function")):
    record = consume_token(db, body.token, "reset")
    user = db.scalar(select(User).where(User.email == record.email))
    if not user:
        raise HTTPException(400, "Account unavailable")
    if record.role == "workspace":
        memberships = list(db.scalars(select(Membership).where(Membership.user_id == user.id)))
        if len(memberships) != 1 or memberships[0].workspace_id != record.workspace_id:
            raise HTTPException(403, "Shared accounts require a self-requested or operator-assisted reset")
    user.password_hash = passwords.hash(body.password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    return {"ok": True}


@router.get("/google/start")
def google_start(
    request: Request,
    invite: str | None = None,
    link: bool = False,
    db: Session = Depends(database, scope="function"),
):
    config = settings()
    if not config.google_client_id or not config.google_client_secret:
        raise HTTPException(
            503, "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )
    user_id = None
    if link:
        user_id = authenticated(request, db)[0].id
    state, nonce, verifier = token(), token(), token()
    db.add(
        OAuthAttempt(
            state_hash=digest(state),
            user_id=user_id,
            provider="google",
            nonce=nonce,
            data={"verifier": verifier, "invite": invite},
            expires_at=now() + 600,
        )
    )
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode(
        {
            "client_id": config.google_client_id,
            "redirect_uri": config.app_url + "/api/v1/auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + query)
    response.set_cookie(
        "sp_oauth",
        state,
        httponly=True,
        secure=config.app_env == "production",
        samesite="lax",
        max_age=600,
        path="/api/v1/auth/google",
    )
    return response


@router.get("/google/callback")
def google_callback(
    request: Request, code: str, state: str, db: Session = Depends(database, scope="function")
):
    if not secrets.compare_digest(request.cookies.get("sp_oauth", ""), state):
        raise HTTPException(400, "OAuth state mismatch")
    attempt = db.scalar(
        select(OAuthAttempt).where(
            OAuthAttempt.state_hash == digest(state),
            OAuthAttempt.provider == "google",
            OAuthAttempt.expires_at > now(),
        )
    )
    if not attempt:
        raise HTTPException(400, "OAuth session expired")
    config = settings()
    try:
        token_response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret,
                "redirect_uri": config.app_url + "/api/v1/auth/google/callback",
                "grant_type": "authorization_code",
                "code_verifier": attempt.data["verifier"],
            },
            timeout=15,
        )
        token_response.raise_for_status()
        jwks = httpx.get("https://www.googleapis.com/oauth2/v3/certs", timeout=15).json()
        from authlib.jose import jwt

        claims = jwt.decode(
            token_response.json()["id_token"],
            jwks,
            claims_options={
                "iss": {"essential": True, "values": ["https://accounts.google.com", "accounts.google.com"]},
                "aud": {"essential": True, "value": config.google_client_id},
                "exp": {"essential": True},
                "nonce": {"essential": True, "value": attempt.nonce},
            },
        )
        claims.validate(leeway=30)
        if not claims.get("email_verified"):
            raise ValueError("Email must be verified")
    except Exception:
        raise HTTPException(400, "Google identity could not be verified; restart sign-in")
    existing = db.scalar(select(User).where(User.google_sub == claims["sub"]))
    if attempt.user_id:
        authenticated_user = authenticated(request, db)[0]
        if authenticated_user.id != attempt.user_id or existing and existing.id != attempt.user_id:
            raise HTTPException(403, "Account linking identity mismatch")
        user = authenticated_user
        user.google_sub = claims["sub"]
    elif existing:
        user = existing
    else:
        email = claims["email"].lower()
        if db.scalar(select(User.id).where(User.email == email)):
            raise HTTPException(
                409, "Sign in with your password first, then explicitly link Google in Settings"
            )
        if not attempt.data.get("invite"):
            raise HTTPException(403, "A workspace invitation is required")
        invitation = consume_token(db, attempt.data["invite"], "invite")
        if invitation.email != email:
            raise HTTPException(403, "Google email does not match the invitation")
        user = User(email=email, name=claims.get("name", email.split("@")[0])[:100], google_sub=claims["sub"])
        db.add(user)
        db.flush()
        db.add(Membership(user_id=user.id, workspace_id=invitation.workspace_id, role=invitation.role))
    if existing and attempt.data.get("invite"):
        invitation = consume_token(db, attempt.data["invite"], "invite")
        if invitation.email != user.email:
            raise HTTPException(403, "Invitation email mismatch")
        if not db.scalar(
            select(Membership.id).where(
                Membership.workspace_id == invitation.workspace_id, Membership.user_id == user.id
            )
        ):
            db.add(Membership(user_id=user.id, workspace_id=invitation.workspace_id, role=invitation.role))
    db.delete(attempt)
    response = RedirectResponse(config.app_url + "/")
    response.delete_cookie("sp_oauth", path="/api/v1/auth/google")
    session_response(db, user, response)
    return response
