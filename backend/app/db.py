import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("sqlite"):
        from pathlib import Path

        Path("data").mkdir(exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def sqlite_pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=10000")
    else:
        engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return engine


engine = make_engine(settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def scope_transaction(session, transaction, connection):
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.workspace_id', :value, true)"),
            {"value": session.info.get("workspace_id", "")},
        )


def set_scope(db: Session, workspace_id: str):
    db.info["workspace_id"] = workspace_id
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.workspace_id', :value, true)"), {"value": workspace_id})


@contextmanager
def session_scope(workspace_id: str | None = None, worker: bool = False):
    factory = SessionLocal
    if worker and settings().worker_database_url:
        global _worker_factory
        if _worker_factory is None:
            _worker_factory = sessionmaker(
                make_engine(settings().worker_database_url), expire_on_commit=False
            )
        factory = _worker_factory
    with factory() as db:
        if workspace_id:
            set_scope(db, workspace_id)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


_worker_factory = None


def create_demo_schema():
    from pathlib import Path
    from alembic import command
    from alembic.config import Config

    if not settings().demo_mode and not os.getenv("PYTEST_CURRENT_TEST"):
        raise RuntimeError("Use Alembic migrations outside demo mode")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
