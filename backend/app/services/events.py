from contextlib import contextmanager
from time import perf_counter

from prometheus_client import Counter, Histogram
from sqlalchemy import func, select

from app.models import Run, RunEvent, now
from app.security import redact

NODES = Histogram("supportpilot_node_duration_seconds", "Graph node duration", ["node"])
ERRORS = Counter("supportpilot_errors_total", "Execution errors", ["kind"])
RETRIES = Counter("supportpilot_retries_total", "Worker retries", ["kind"])
TOOLS = Counter("supportpilot_tool_outcomes_total", "Outbound outcomes", ["kind", "status"])


def emit(db, run, node, status, data=None, duration_ms=None):
    # Workers hold a per-run lock. API decisions lock the run before appending events.
    db.flush()
    db.execute(select(Run.id).where(Run.id == run.id, Run.workspace_id == run.workspace_id).with_for_update())
    seq = (db.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run.id)) or 0) + 1
    event = RunEvent(
        workspace_id=run.workspace_id,
        run_id=run.id,
        sequence=seq,
        node=node,
        status=status,
        data=redact(data or {}),
        duration_ms=duration_ms,
    )
    db.add(event)
    run.current_node = node
    run.updated_at = now()
    db.commit()
    return event


@contextmanager
def trace(db, run, node):
    start = perf_counter()
    emit(db, run, node, "running")
    try:
        yield
    except BaseException as exc:
        emit(db, run, node, "failed", {"error": str(exc)}, int((perf_counter() - start) * 1000))
        raise
    else:
        elapsed = perf_counter() - start
        NODES.labels(node).observe(elapsed)
        emit(db, run, node, "completed", duration_ms=int(elapsed * 1000))
