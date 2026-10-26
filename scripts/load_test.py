"""Opt-in isolated demo workload. Never invokes live providers; outputs a hardware-labelled report."""

import argparse
import concurrent.futures
import json
import os
import platform
import statistics
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    if httpx.get(args.url + "/api/health").json().get("demo_mode") is not True:
        raise SystemExit("Load fixtures may only target DEMO_MODE=true")
    os.environ.setdefault("DEMO_MODE", "true")
    from app.db import session_scope
    from app.models import AuthSession, Membership, User, Workspace, now
    from app.security import digest, token

    users = []
    with session_scope(worker=True) as db:
        workspaces = [Workspace(name=f"Load fixture {i + 1}") for i in range(10)]
        db.add_all(workspaces)
        db.flush()
        for i in range(args.users):
            user = User(name=f"Load user {i}", email=f"load-{token()[:10]}@example.com")
            db.add(user)
            db.flush()
            workspace = workspaces[i % len(workspaces)]
            db.add(Membership(workspace_id=workspace.id, user_id=user.id, role="agent"))
            raw, csrf = token(), token()
            db.add(
                AuthSession(
                    user_id=user.id,
                    token_hash=digest(raw),
                    csrf_token=csrf,
                    expires_at=now() + 1800,
                )
            )
            users.append((workspace.id, raw, csrf))
    started = time.perf_counter()

    def send(item):
        workspace, raw, csrf = item
        with httpx.Client(
            base_url=args.url, cookies={"sp_session": raw}, timeout=30
        ) as client:
            begin = time.perf_counter()
            response = client.post(
                "/api/v1/runs",
                json={
                    "prompt": "Summarize our support documentation; do not propose an outbound action."
                },
                headers={
                    "X-CSRF-Token": csrf,
                    "X-Workspace-ID": workspace,
                    "Idempotency-Key": token(),
                },
            )
            response.raise_for_status()
            return {
                "workspace": workspace,
                "cookie": raw,
                "id": response.json()["id"],
                "latency_ms": (time.perf_counter() - begin) * 1000,
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(send, users))
    dispatch_elapsed = time.perf_counter() - started
    pending = {r["id"]: r for r in results}
    deadline = time.time() + 180
    outcomes = {}
    while pending and time.time() < deadline:
        for identifier, item in list(pending.items()):
            response = httpx.get(
                args.url + "/api/v1/runs/" + identifier,
                cookies={"sp_session": item["cookie"]},
                headers={"X-Workspace-ID": item["workspace"]},
            )
            response.raise_for_status()
            status = response.json()["status"]
            if status in {
                "completed",
                "failed",
                "awaiting_approval",
                "needs_attention",
            }:
                outcomes[status] = outcomes.get(status, 0) + 1
                pending.pop(identifier)
        if pending:
            time.sleep(0.5)
    latencies = sorted(r["latency_ms"] for r in results)
    report = {
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "users": args.users,
        "workspaces": 10,
        "http_concurrency": args.concurrency,
        "provider_mode": "deterministic demo fixtures",
        "dispatch_seconds": round(dispatch_elapsed, 2),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(latencies[int(len(latencies) * 0.95) - 1], 2),
        "outcomes": outcomes,
        "unfinished": len(pending),
        "note": "HTTP concurrency is not proof of simultaneous worker execution. Use scaled Celery workers for that measurement.",
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/load-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    if pending or outcomes.get("failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
