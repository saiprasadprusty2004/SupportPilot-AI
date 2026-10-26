from fastapi import HTTPException
from sqlalchemy import and_, or_, select


def page(db, cls, workspace_id, limit=30, cursor=None, conditions=()):
    query = select(cls).where(cls.workspace_id == workspace_id, *conditions)
    if cursor:
        try:
            stamp, identifier = cursor.split("|", 1)
            query = query.where(
                or_(cls.created_at < float(stamp), and_(cls.created_at == float(stamp), cls.id < identifier))
            )
        except ValueError:
            raise HTTPException(400, "Invalid cursor")
    rows = list(db.scalars(query.order_by(cls.created_at.desc(), cls.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, f"{rows[-1].created_at}|{rows[-1].id}" if rows and more else None


def public(obj, exclude=()):
    hidden = {
        "password_hash",
        "google_sub",
        "stripe_key_ciphertext",
        "token_hash",
        "csrf_token",
        "state_hash",
        "nonce",
        "sync_cursor",
        "lease_owner",
        *exclude,
    }
    return {
        column.name: getattr(obj, column.name)
        for column in obj.__table__.columns
        if column.name not in hidden
    }
