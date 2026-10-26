import logging
import time

from sqlalchemy import delete

from app.config import settings
from app.db import session_scope
from app.models import AuthSession, OAuthAttempt, RateBucket, now
from app.services.jobs import dispatch_once, schedule_mailboxes

logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","message":"%(message)s"}')


def main():
    settings().validate_runtime()
    cleanup_at = 0
    while True:
        try:
            dispatch_once(demo=settings().demo_mode)
            schedule_mailboxes()
            if now() > cleanup_at:
                with session_scope(worker=True) as db:
                    for cls in (AuthSession, OAuthAttempt, RateBucket):
                        db.execute(delete(cls).where(cls.expires_at < now()))
                cleanup_at = now() + 3600
        except Exception:
            logging.exception("scheduler_iteration_failed")
        time.sleep(2)


if __name__ == "__main__":
    main()
