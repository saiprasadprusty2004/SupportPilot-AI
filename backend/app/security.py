import hashlib
import json
import re
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, set_scope
from app.models import Audit, AuthSession, Membership, RateBucket, User, now

passwords = PasswordHasher()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def payload_hash(value) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")))


def token() -> str:
    return secrets.token_urlsafe(32)


def check_password(encoded: str | None, value: str) -> bool:
    try:
        return bool(encoded and passwords.verify(encoded, value))
    except (VerificationError, InvalidHashError):
        return False


def encrypt(value: str) -> str:
    key = settings().encryption_key
    if not key:
        raise HTTPException(503, "Set ENCRYPTION_KEY before storing credentials")
    return Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return Fernet(settings().encryption_key.encode()).decrypt(value.encode()).decode()


SECRET_FIELDS = re.compile(r"password|token|secret|authorization|api.?key|cookie|credential", re.I)
SECRET_VALUES = re.compile(r"(?i)(?:sk|rk)_(?:test|live)_[\w-]+|gsk_[\w-]+|Bearer\s+[\w.\-]+")


def redact(value, depth=0):
    if depth > 8:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(k): "[redacted]" if SECRET_FIELDS.search(str(k)) else redact(v, depth + 1)
            for k, v in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in value[:100]]
    if isinstance(value, str):
        return SECRET_VALUES.sub("[redacted]", value)[:12000]
    return value


def database():
    # All consumers use function scope: commit before the HTTP response/cookie is sent.
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


@dataclass
class Identity:
    user: User
    membership: Membership
    session: AuthSession

    @property
    def workspace_id(self):
        return self.membership.workspace_id


def authenticated(
    request: Request, db: Session = Depends(database, scope="function")
) -> tuple[User, AuthSession]:
    raw = request.cookies.get("sp_session", "")
    record = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == digest(raw), AuthSession.expires_at > now())
    )
    if not record:
        raise HTTPException(401, "Sign in to continue")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), record.csrf_token):
            raise HTTPException(403, "Invalid CSRF token")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != settings().app_url.rstrip("/"):
            raise HTTPException(403, "Invalid request origin")
    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(401, "Account unavailable")
    return user, record


def identity(
    request: Request,
    auth=Depends(authenticated, scope="function"),
    db: Session = Depends(database, scope="function"),
) -> Identity:
    user, session = auth
    query = select(Membership).where(Membership.user_id == user.id)
    selected = request.headers.get("X-Workspace-ID")
    if request.method == "GET" and (
        request.url.path.endswith("/source") or request.url.path.endswith("/stream")
    ):
        selected = selected or request.query_params.get("workspace_id")
    if selected:
        query = query.where(Membership.workspace_id == selected)
    membership = db.scalar(query.order_by(Membership.created_at))
    if not membership:
        raise HTTPException(403, "Workspace access denied")
    set_scope(db, membership.workspace_id)
    return Identity(user, membership, session)


def owner(who: Identity = Depends(identity, scope="function")) -> Identity:
    if who.membership.role != "owner":
        raise HTTPException(403, "Workspace owner access required")
    return who


def tenant_get(db: Session, cls, identifier: str, workspace_id: str):
    obj = db.scalar(select(cls).where(cls.id == identifier, cls.workspace_id == workspace_id))
    if not obj:
        raise HTTPException(404, "Resource not found")
    return obj


def audit(db, who: Identity, event: str, entity_id: str, data=None):
    db.add(
        Audit(
            workspace_id=who.workspace_id,
            user_id=who.user.id,
            event=event,
            entity_id=entity_id,
            data=redact(data or {}),
        )
    )


def throttle(db: Session, key: str, limit: int, window: int = 60):
    # Persistent and shared across API replicas. Lock/update the bucket atomically.
    bucket_key = f"{key}:{int(now() // window)}"
    if not db.get(RateBucket, bucket_key):
        dialect = db.bind.dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        db.execute(
            insert(RateBucket)
            .values(key=bucket_key, count=0, expires_at=now() + window)
            .on_conflict_do_nothing(index_elements=["key"])
        )
    count = db.execute(
        update(RateBucket)
        .where(RateBucket.key == bucket_key)
        .values(count=RateBucket.count + 1)
        .returning(RateBucket.count)
    ).scalar_one()
    db.commit()
    if count > limit:
        raise HTTPException(429, "Too many requests; try again shortly", headers={"Retry-After": str(window)})
