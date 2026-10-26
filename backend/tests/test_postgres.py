"""Real PostgreSQL coverage. CI supplies a migrated database; local runs skip without its URL."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.postgres
def test_app_role_cannot_bypass_rls_or_read_checkpoints():
    url = os.getenv("POSTGRES_TEST_URL")
    admin_url = os.getenv("POSTGRES_ADMIN_TEST_URL")
    if not url or not admin_url:
        pytest.skip("Set POSTGRES_TEST_URL and POSTGRES_ADMIN_TEST_URL after migrations")
    app_engine, admin = create_engine(url), create_engine(admin_url)
    workspace_a, workspace_b, document_a, document_b, user = [str(uuid4()) for _ in range(5)]
    try:
        with admin.begin() as db:
            db.execute(
                text("INSERT INTO users(id,created_at,email,name) VALUES (:id,0,:email,'RLS Test')"),
                {"id": user, "email": user + "@example.com"},
            )
            for workspace, document in [(workspace_a, document_a), (workspace_b, document_b)]:
                db.execute(
                    text("INSERT INTO workspaces(id,created_at,name,slack_channel) VALUES (:id,0,'RLS','')"),
                    {"id": workspace},
                )
                db.execute(
                    text("""INSERT INTO documents(id,workspace_id,uploaded_by,created_at,name,storage_key,
                  mime_type,size,status,version,content_hash,embedding_config) VALUES
                  (:id,:ws,:u,0,'Secret','key','text/plain',10,'ready',1,'hash','{}')"""),
                    {"id": document, "ws": workspace, "u": user},
                )
        with app_engine.begin() as db:
            assert db.scalar(text("SELECT count(*) FROM documents")) == 0
            db.execute(text("SELECT set_config('app.workspace_id',:ws,true)"), {"ws": workspace_a})
            ids = list(db.scalars(text("SELECT id FROM documents")))
            assert document_a in ids and document_b not in ids
            assert not db.scalar(text("SELECT has_table_privilege(current_user,'checkpoints','SELECT')"))
        with app_engine.connect() as db:
            with pytest.raises(Exception):
                db.execute(text("SET ROLE supportpilot_worker"))
    finally:
        with admin.begin() as db:
            db.execute(text("DELETE FROM documents WHERE id IN (:a,:b)"), {"a": document_a, "b": document_b})
            db.execute(
                text("DELETE FROM workspaces WHERE id IN (:a,:b)"), {"a": workspace_a, "b": workspace_b}
            )
            db.execute(text("DELETE FROM users WHERE id=:id"), {"id": user})
        app_engine.dispose()
        admin.dispose()


@pytest.mark.postgres
def test_real_semantic_pgvector_rag_with_tenant_filter(env, monkeypatch):
    if not os.getenv("RUN_EMBEDDING_TESTS") or not os.getenv("POSTGRES_TEST_URL"):
        pytest.skip("Requires PostgreSQL roles and RUN_EMBEDDING_TESTS=1 with the local model installed")
    import math
    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session
    from app.config import settings
    from app.db import set_scope
    from app.models import Chunk, Document, User, Workspace, now
    from app.services.knowledge import index_document, search
    from app.services.storage import storage

    api_engine = create_engine(os.environ["POSTGRES_TEST_URL"])
    worker = create_engine(os.environ["WORKER_DATABASE_URL"])
    monkeypatch.setattr(settings(), "demo_mode", False)
    workspace_ids, document_ids, user_id = [], [], str(uuid4())
    keys = []
    try:
        with Session(worker) as db:
            db.add(User(id=user_id, name="Semantic fixture", email=user_id + "@example.com"))
            for name in ("Semantic A", "Semantic B"):
                workspace = Workspace(name=name)
                db.add(workspace)
                db.flush()
                workspace_ids.append(workspace.id)
            for i, (workspace_id, name, content) in enumerate(
                [
                    (
                        workspace_ids[0],
                        "Payments.md",
                        "If a customer was charged twice for one order, return the extra payment after an owner reviews the transaction.",
                    ),
                    (
                        workspace_ids[0],
                        "Plants.md",
                        "Trees and yellow flowers grow in a garden with sunlight and water.",
                    ),
                    (
                        workspace_ids[1],
                        "Private.md",
                        "Reimburse a duplicate invoice charge. Private workspace policy, never publish outside this tenant.",
                    ),
                ]
            ):
                key = f"{workspace_id}/{uuid4()}/v1"
                storage().put(key, content.encode())
                keys.append(key)
                doc = Document(
                    workspace_id=workspace_id,
                    uploaded_by=user_id,
                    name=name,
                    storage_key=key,
                    mime_type="text/markdown",
                    size=len(content),
                    content_hash=str(i),
                )
                db.add(doc)
                db.commit()
                document_ids.append(doc.id)
                index_document(db, doc)
            for chunk in db.scalars(select(Chunk).where(Chunk.document_id.in_(document_ids))):
                assert len(chunk.embedding) == 384
                assert math.isclose(sum(float(v) ** 2 for v in chunk.embedding), 1, abs_tol=0.001)
        with Session(api_engine) as db:
            set_scope(db, workspace_ids[0])
            hits = search(db, workspace_ids[0], "How can we reimburse a duplicate invoice charge?")
            assert hits and hits[0]["document_id"] == document_ids[0]
            assert all(hit["document_id"] != document_ids[2] for hit in hits)
            assert hits[0]["version"] == 1 and "version=1" in hits[0]["url"]
        with Session(worker) as db:
            db.get(Document, document_ids[0]).deleted_at = now()
            db.commit()
        with Session(api_engine) as db:
            set_scope(db, workspace_ids[0])
            assert all(
                hit["document_id"] != document_ids[0]
                for hit in search(db, workspace_ids[0], "reimburse duplicate charge")
            )
    finally:
        with worker.begin() as db:
            db.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))
            db.execute(delete(Document).where(Document.id.in_(document_ids)))
            db.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
            db.execute(delete(User).where(User.id == user_id))
        for key in keys:
            storage().delete(key)
        api_engine.dispose()
        worker.dispose()
