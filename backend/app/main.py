import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from sqlalchemy import func, select, text

from app.api import auth, connections, knowledge, runs, workspaces
from app.config import settings
from app.db import create_demo_schema, session_scope
from app.models import Action, Job, now
from app.services.providers import ProviderError

logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","message":"%(message)s"}')
QUEUE_AGE = Gauge("supportpilot_oldest_job_age_seconds", "Age of oldest runnable job")
WAITING = Gauge("supportpilot_pending_approvals", "Pending human approvals")
DEAD_LETTERS = Gauge("supportpilot_dead_letter_jobs", "Jobs requiring operator recovery")


async def demo_scheduler(stop):
    from app.services.jobs import dispatch_once

    while not stop.is_set():
        try:
            await asyncio.to_thread(dispatch_once, True)
        except Exception:
            logging.exception("demo_dispatch_failed")
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app):
    config = settings()
    config.validate_runtime()
    stop = asyncio.Event()
    task = None
    if config.demo_mode:
        if config.database_url.startswith("sqlite"):
            create_demo_schema()
        if not os.getenv("SUPPORTPILOT_TESTING"):
            from app.seed import seed_demo

            seed_demo()
            if config.database_url.startswith("sqlite"):
                task = asyncio.create_task(demo_scheduler(stop))
    yield
    if task:
        stop.set()
        await task


app = FastAPI(
    title="SupportPilot API",
    version="0.1.0",
    lifespan=lifespan,
    description="Workspace-isolated, approval-driven support automation.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings().app_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Workspace-ID", "Idempotency-Key", "Last-Event-ID"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > 26 * 1024 * 1024:
        return JSONResponse({"detail": "Request exceeds 26 MB"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ProviderError)
async def provider_error(request, exc):
    return JSONResponse({"detail": str(exc), "retryable": exc.transient}, status_code=503)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(
        {"detail": exc.detail, "error": {"code": exc.status_code, "message": exc.detail}},
        status_code=exc.status_code,
        headers=exc.headers,
    )


for router in [auth.router, workspaces.router, connections.router, knowledge.router, runs.router]:
    app.include_router(router, prefix="/api/v1")


@app.get("/api/health", tags=["operations"])
def health():
    with session_scope() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "demo_mode": settings().demo_mode}


@app.get("/api/ready", tags=["operations"])
def ready():
    health()
    if not settings().demo_mode:
        from redis import Redis

        try:
            Redis.from_url(settings().redis_url, socket_timeout=2).ping()
        except Exception:
            raise HTTPException(503, "Redis is unavailable")
    return {"status": "ready"}


@app.get("/internal/metrics", include_in_schema=False)
def metrics():
    # Routed only on the private Docker network. Caddy never exposes /internal.
    with session_scope(worker=True) as db:
        if db.bind.dialect.name == "postgresql":
            row = db.execute(text("SELECT * FROM public.supportpilot_operational_metrics()")).mappings().one()
            QUEUE_AGE.set(max(0, now() - row["oldest_pending"]) if row["oldest_pending"] else 0)
            WAITING.set(row["pending_approvals"])
            DEAD_LETTERS.set(row["dead_letters"])
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
        oldest = db.scalar(
            select(func.min(Job.created_at)).where(Job.status.in_(["pending", "queued", "retrying"]))
        )
        QUEUE_AGE.set(max(0, now() - oldest) if oldest else 0)
        WAITING.set(
            db.scalar(select(func.count()).select_from(Action).where(Action.status == "pending")) or 0
        )
        DEAD_LETTERS.set(
            db.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.status.in_(["dead_letter", "needs_attention"]))
            )
        )
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
