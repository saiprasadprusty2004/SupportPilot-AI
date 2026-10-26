"""Initial schema, vector search indexes, and role-separated tenant policies."""

from alembic import op

from app.db import Base
from app import models  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCOPED = [
    "connections",
    "documents",
    "document_versions",
    "chunks",
    "tickets",
    "messages",
    "runs",
    "run_events",
    "actions",
    "tool_executions",
    "jobs",
    "outbox",
    "audit",
]


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind)
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX chunks_fts ON chunks USING gin (to_tsvector('english', text))")
    for table in Base.metadata.tables:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO supportpilot_app, supportpilot_worker'
        )
    for table in SCOPED:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'''CREATE POLICY workspace_isolation ON "{table}"
          USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')
                 OR current_user = 'supportpilot_worker')
          WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), '')
                 OR current_user = 'supportpilot_worker')''')
    op.execute("GRANT USAGE ON SCHEMA public TO supportpilot_app, supportpilot_worker")
    op.execute("GRANT CREATE ON SCHEMA public TO supportpilot_worker")


def downgrade():
    raise RuntimeError("Initial schema downgrade is destructive. Restore a verified backup instead.")
