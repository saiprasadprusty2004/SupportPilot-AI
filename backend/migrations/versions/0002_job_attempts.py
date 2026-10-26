"""Durable attempts and immutable acting-account snapshots for approvals."""

from alembic import op
from sqlalchemy import Column, String, inspect
from app.models import JobAttempt

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    JobAttempt.__table__.create(bind, checkfirst=True)
    existing = {column["name"] for column in inspect(bind).get_columns("actions")}
    for name, length in [("provider_account_id", 255), ("acting_account_label", 254)]:
        if name not in existing:
            op.add_column("actions", Column(name, String(length), nullable=True))
    if bind.dialect.name == "postgresql":
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON job_attempts TO supportpilot_app, supportpilot_worker"
        )
        op.execute("ALTER TABLE job_attempts ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE job_attempts FORCE ROW LEVEL SECURITY")
        op.execute("""CREATE POLICY workspace_isolation ON job_attempts
          USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')
                 OR current_user = 'supportpilot_worker')
          WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), '')
                 OR current_user = 'supportpilot_worker')""")
        # The API can expose private operational counts without worker credentials or row access.
        op.execute("""CREATE OR REPLACE FUNCTION public.supportpilot_operational_metrics()
          RETURNS TABLE(oldest_pending double precision, pending_approvals bigint, dead_letters bigint)
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
            SELECT (SELECT min(created_at) FROM public.jobs WHERE status IN ('pending','queued','retrying')),
                   (SELECT count(*) FROM public.actions WHERE status='pending'),
                   (SELECT count(*) FROM public.jobs WHERE status IN ('dead_letter','needs_attention'))
          $$""")
        op.execute("REVOKE ALL ON FUNCTION public.supportpilot_operational_metrics() FROM PUBLIC")
        op.execute("ALTER FUNCTION public.supportpilot_operational_metrics() OWNER TO supportpilot_worker")
        op.execute(
            "GRANT EXECUTE ON FUNCTION public.supportpilot_operational_metrics() TO supportpilot_app, supportpilot_worker"
        )


def downgrade():
    raise RuntimeError("Attempt history is audit data. Restore a verified backup for rollback.")
