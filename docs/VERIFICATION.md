# Verification and operating limits

## Modes

| Mode | Data and models | Purpose |
| --- | --- | --- |
| `/preview` | Browser-only illustrative fixtures | Explore design, themes, responsive layouts, and safe UI interactions. |
| SQLite demo | Real API/database/checkpoints, lexical retrieval fixture, simulated providers | Reproduce uploads, runs, approvals, recovery, and history without credentials. |
| Compose demo | PostgreSQL/Redis/Celery/checkpoints, simulated providers | Validate distributed infrastructure without external actions. |
| Live pilot | Groq, pinned local sentence-transformer, pgvector, Composio, Stripe test API | Process connected accounts under approval policies. |

## Automated coverage

- Backend integration suite exercises authentication, CSRF, invitation/reset replay, Google PKCE/OIDC signature and nonce verification, workspace and connection ownership, document ingestion/search/deletion, approval edit/resume/rejection, stale-target and payload checks, idempotency, quota parks, exponential retries, worker lease recovery, broker outage, uncertain-send reconciliation, and Stripe adapter behavior.
- PostgreSQL CI applies the initial migration with pgvector and role-separated credentials, provisions checkpoint tables, and checks RLS isolation, checkpoint privilege denial, and role escalation denial. Local runs skip this test without `POSTGRES_TEST_URL` and `POSTGRES_ADMIN_TEST_URL`.
- Browser suite covers light/dark themes at desktop/mobile sizes, no horizontal overflow, theme switching, chat, knowledge search, approval edits, preview-only actions, execution traces, and reduced-motion fallback. Screenshots and failure traces are stored in ignored test-result directories.
- The full-stack browser smoke test is opt-in with `DEMO_E2E_URL`. It uses the real API and persistent demo workflow. Real OAuth-provider consent is not simulated by a browser click-through.
- Provider smoke tests are read-only and opt-in with `RUN_LIVE_TESTS=1`. Real semantic embedding evaluation requires `RUN_EMBEDDING_TESTS=1` and the embeddings extra/model download. No smoke test sends email, posts messages, or issues a refund.
- The initial JavaScript budget is measured from Vite's manifest, recursively counting every static import. Lazy 3D chunks are checked for accidental eager inclusion. Target: at most 300 KB gzip.

## Performance profile

Use a production build (`npm run build`, then `npm run preview -- --port 4173`). Measure `/preview` in a clean Chromium profile with Lighthouse's simulated mobile throttling; record browser version, CPU, viewport, and mode. Targets are performance ≥90, LCP ≤2.5 seconds, and CLS ≤0.1. Device-dependent WebGL frame rate is a target, not a universal guarantee; the application adapts or falls back when needed.

Run the isolated load harness against a disposable demo database:

```sh
python scripts/load_test.py --url http://127.0.0.1:8000 --users 100 --concurrency 20
```

The harness creates 10 named load-fixture workspaces and 100 temporary users/sessions. It sends 100 tasks through 20 concurrent HTTP clients, waits for terminal outcomes, and records hardware, p50/p95 request latency, elapsed time, and outcomes in `artifacts/load-report.json`. It intentionally refuses live mode. Use a disposable database because fixture rows are retained for inspection. HTTP concurrency does not establish simultaneous worker execution: test that separately with 20 scaled Celery slots and provider fixtures.

## Limits and remaining operational requirements

- Configure actual provider scopes and public HTTPS callback verification before using live OAuth. A connected account is checked against the expected Composio identity, toolkit, and auth config on use.
- Free Groq quotas apply to the shared operator account. Settings are conservative reservations, not a way to guarantee throughput or avoid upstream throttling.
- PDF extraction is bounded to 500 pages and two million characters; scanned PDFs need an external OCR step. DOCX expanded size is capped at 100 MB; files are capped at 25 MB at both proxy and application boundaries.
- Graph executions are bounded to 12 model/tool steps; approvals expire after 24 hours. Unknown external outcomes require evidence-based reconciliation. API owners cannot reset accounts shared across unrelated workspaces.
- Checkpoints contain private task context. Only trusted workers and database administrators can access their tables. Plan retention and backup policies before processing real customer data.
- Prometheus node/retry counters are process-local. Production monitoring should scrape worker processes with a multiprocess collector or central metrics sidecar; the included private API endpoint provides health/queue instrumentation for the pilot, not a complete hosted monitoring stack.
- No public host, CI run, real OAuth grant, live model call, or external communication is implied by successful fixture tests. Deployment depends on a working Docker engine and configured secrets.

## Recorded local results — 2026-10-26

Hardware: Windows 11 build 26200, AMD Ryzen 5 3600 (6 cores / 12 logical CPUs), 15.9 GiB RAM. Local core tests use Python 3.14; deployment and CI target Python 3.12. Browser verification uses Chromium 156.

| Check | Observed result |
| --- | --- |
| Backend integration suite | 49 passed, 5 skipped. Covers live-mode HTTP adapter fixtures, cited edited approvals, stale-source replanning, account changes, concurrent decisions, intake ordering/deduplication, tenant isolation, retry/dead-letter recovery, worker-loss reconciliation, and commit-before-cookie ordering. |
| Real local MiniLM smoke | 1 passed using cached pinned model, offline. Validates normalized 384-dimensional semantic embeddings and similarity ordering independently of the lexical demo fixture. |
| Browser suite against real local API | 20 passed, 2 intentional mobile skips. Upload/indexing, source download, Gmail draft edit/approve, Slack proposal/approval, test payment linking/refund, duplicate decisions, SSE replay, invitation/password login, role restrictions, both-theme accessibility, 360 px layout, WebGL scene and fallback. |
| Frontend build/type checking | Passed. Initial application JavaScript: 137.0 KB gzip including static imports; 3D remains lazy. |
| Lighthouse production mobile profile | Performance 95; accessibility 100; LCP 2,269 ms; CLS 0. Uses simulated mobile throttling and the static small-screen scene, not a desktop WebGL FPS measurement. |
| Source checks | Ruff, OpenAPI/type generation, workflow YAML syntax, Compose configuration, and all 105 file-guide entries passed. |
| Shipped JavaScript dependencies | `npm audit --omit=dev` reported zero vulnerabilities at verification time. |

The disposable SQLite fixture load run used 10 workspaces, 100 user sessions, and 20 concurrent HTTP clients. All 100 tasks completed; none remained unfinished. Dispatch took 10.43 seconds and total completion took 45.70 seconds. Run-creation latency was p50 17.05 ms / p95 55.95 ms. This measures application requests, durable demo workflows, checkpoints, and dispatch; it does **not** establish 20 simultaneous PostgreSQL/Celery workflow executions or real-provider throughput. Reports are generated in ignored `artifacts/load-report.json` and `artifacts/lighthouse.{json,html}`.

The five default backend skips are the PostgreSQL RLS test, PostgreSQL/Redis/Celery checkpoint round trip, real MiniLM/pgvector retrieval test, credential-gated Groq smoke, and opt-in local-model test. The local-model test was run separately as recorded above. CI provisions PostgreSQL/Redis and installs CPU embedding dependencies for the real semantic retrieval test; that CI run has not been executed from this workspace.

Local container verification is blocked by Docker Desktop failing to initialize its `dockerInference` socket; its engine API did not become ready. No host configuration was changed to bypass that failure. Real Groq/Composio/Google credentials and least-privilege auth-config IDs are not present in the local environment. Real OAuth consent, authenticated provider smoke checks, container builds, database role/migration checks, and a 20-worker distributed load test remain required before a live pilot. Configure secrets locally using `.env.example`; do not paste them into chat.
