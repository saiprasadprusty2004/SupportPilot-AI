# SupportPilot

A thoughtful support workspace with a light/dark dashboard, adaptive 3D graphics, cited document search, durable LangGraph workflows, and owner-approved actions.

**Start with [FILE_GUIDE.md](FILE_GUIDE.md)** for the explanation of every repository file, architecture diagrams, lifecycle walkthroughs, configuration, and extension points.

## Explore locally

The frontend design preview is available at **[http://localhost:5173/preview](http://localhost:5173/preview)** while the development server is running. It requires no login or provider keys. Its sample metrics and interactions are explicitly illustrative; it never sends email, posts Slack messages, or refunds money.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "./backend[test]"
cd frontend
npm.cmd ci
npm.cmd run dev
```

For the **working full-stack local demo**, also run this from the repository root in another terminal:

```powershell
.\.venv\Scripts\python.exe -m app.cli demo
```

Open [http://localhost:5173](http://localhost:5173), choose **Open demo workspace**, and try Inbox → Prepare reply → Approvals → Review & edit → Approve. The demo uses SQLite, persistent graph checkpoints, deterministic lexical retrieval fixtures, and simulated outbound actions. Uploaded files and approvals really persist, but demo retrieval is not a substitute for the live semantic embedding path.

Python 3.12 is the deployment target; the core demo also runs on Python 3.14. Linux/macOS use `.venv/bin/python` and `npm` instead of the Windows executable names.

## Docker Compose

With Docker Desktop/Engine running:

```sh
docker compose up --build -d
docker compose ps
```

Open [http://localhost:8080](http://localhost:8080). Compose creates PostgreSQL/pgvector, Redis, migrations/checkpoints, API, workers, scheduler, and the frontend proxy. The default is a clearly labelled demo. The first image build installs CPU embedding dependencies and can take several minutes.

Keep the local Python demo and the Compose demo separate: they have different databases. `docker compose down` preserves volumes. Do not remove volumes unless their data is disposable.

## Enable real integrations

1. Copy `.env.example` to `.env`. Generate fresh secrets with `python -m app.cli generate-secrets`. Set `DEMO_MODE=false`, the three database URLs, encryption key, and provider configuration. Database role passwords and URLs must agree.
2. Add a Groq API key. Check your account's quota and enable its zero-data-retention controls before processing private tickets. Set conservative shared request/token budgets. Free quotas can pause runs; no paid provider fallback is used.
3. Create three least-privilege Composio auth configs and enter their IDs. Configure the project callback identity verifier as `https://YOUR_DOMAIN/api/v1/connections/callback`. Composio requires public HTTPS for this verifier; local live OAuth therefore needs a secure tunnel and a matching `APP_URL`. Google scopes may require your own verified OAuth app even though Composio retains token custody.
4. Optional Google app sign-in uses a separate OIDC client, `openid email profile`, and redirect URI `APP_URL/api/v1/auth/google/callback`. Existing password users explicitly link Google through Settings; accounts are never merged by email alone.
5. Apply migrations and provision checkpoints, then create an owner:

```sh
docker compose run --rm migrate
docker compose run --rm api python -m app.cli bootstrap --email owner@example.com --workspace "My team"
docker compose up -d
```

6. Sign in, connect personal Gmail/Slack/Drive accounts, and explicitly enable the owner-approval policy. Use a Gmail **label ID**, such as `INBOX` or `Label_123`; new-message intake starts at activation. A separate backfill endpoint imports the previous seven days.
7. Add product documents or explicitly publish selected Drive snapshots. Set an allowed Slack channel ID in Settings. For refunds, store a workspace **Stripe test key**, then use **Inbox → Link test payment → Propose test refund**. The server verifies the payment with that workspace key. Live Stripe keys/payments are rejected.

Owners can invite agents or other owners, create expiring password-reset links, and remove members in Settings. Removing access disables the member's connected automation. Approvals show the acting account; reconnecting another account or changing a Stripe key requires fresh planning and approval. Run details include persisted job-attempt history as well as graph events.

Provider setup references: [Composio authentication](https://docs.composio.dev/docs/authentication), [callback identity verification](https://docs.composio.dev/reference/api-reference/connected-accounts), [Groq data controls](https://console.groq.com/docs/your-data), [Groq quotas](https://console.groq.com/docs/rate-limits).

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\ruff.exe check backend scripts
.\.venv\Scripts\python.exe scripts/check_file_guide.py
.\.venv\Scripts\python.exe scripts/export_openapi.py
cd frontend
npm.cmd run generate:api
npm.cmd run build
npm.cmd run test:e2e
cd ..
node scripts/check_bundle.mjs
```

Install the browser once with `npx playwright install chromium`. PostgreSQL RLS tests require migrated database URLs; live provider and real-model smoke tests require explicit environment opt-in. CI supplies PostgreSQL/Redis and verifies migrations and RLS independently of SQLite tests. See [verification notes](docs/VERIFICATION.md).

To exercise the full browser journey, run a disposable demo API with `APP_URL=http://127.0.0.1:4173`, then set `DEMO_E2E_URL=http://127.0.0.1:4173` for `npm run test:e2e`. Playwright starts the production frontend and proxies API calls to port 8000. Use the exact browser origin in `APP_URL`; CSRF checks intentionally reject a different host or port. The journey uploads a document, edits and approves a cited draft, performs simulated Gmail/Slack/refund actions, replays SSE history, and tests invitation/password login.

## Server deployment and scaling

Use Compose 2.24.4+ for the production override. Configure a domain pointing to your server, `APP_ENV=production`, `DEMO_MODE=false`, HTTPS `APP_URL`, random database passwords, and all secrets. Then:

```sh
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

Only the reverse proxy exposes public ports. Caddy obtains TLS certificates and proxies SSE without buffering. PostgreSQL/Redis stay private. The API database role cannot read workflow checkpoints; the trusted worker role has cross-workspace access for scheduling and execution. Application policies additionally constrain every action to its originating connection and approved payload.

Scale workers independently, keeping the application-wide limit at 20 and workspace limit at 2:

```sh
docker compose up -d --scale worker=5
```

Five four-process worker containers give 20 execution slots; actual throughput depends on model/provider quotas, CPU, memory, and task duration. For multiple hosts, select S3 storage and managed PostgreSQL/Redis. Give queue-specific workers the `agent`, `ingestion`, or `outbound` queue to prevent slow document jobs blocking dispatch. Use one scheduler or rely on durable claims for duplicate-safe dispatch.

Release tags publish images to GHCR. Deployment is manually dispatched and protected by a GitHub `production` environment, SSH host-key verification, and configured server secrets. No cloud resources or paid accounts are provisioned automatically.

## Recovery and backups

Use `sh scripts/backup.sh` for PostgreSQL and uploads; store backups encrypted and keep `ENCRYPTION_KEY` separately. To restore, stop API/workers/scheduler, restore the database dump with `pg_restore` into a matching migrated database, restore uploads, restore the original encryption key, and restart. Test restoration on an isolated server before relying on a backup.

Failed jobs remain inspectable as dead letters. Unknown Gmail/Slack outcomes require an owner to inspect the provider and record reconciliation evidence; **never blindly replay a send**. Stripe uses a stable provider idempotency key and refund metadata for recovery, with a conservative 23-hour automatic retry window. Approval, action, and checkpoint history survive restarts.

This is a small-team pilot implementation. Public SaaS billing, OCR, live refunds, automatic Drive synchronization, and cloud provisioning are intentionally excluded. Provider credentials and a healthy deployment are required for live operation.
