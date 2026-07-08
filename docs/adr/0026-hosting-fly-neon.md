# ADR-0026: Hosting — Fly.io (single pinned machine) + Neon Postgres

- **Status:** accepted
- **Date:** 2026-07-08
- **Deciders:** leejianrong, Claude
- **Answers:** QUESTIONS **K3** (hosting target; serverless-vs-WebSockets). Touches K4 (sizing, still open), builds on ADR-0018/0020 (single in-memory worker), ADR-0005 (stack), ADR-0013/0014 (auth).

## Context
The MVP runs as **one game-worker process with authoritative state in memory** (ADR-0018/0020): board, clocks, the matchmaking queue, and all bot WebSockets live in a single process. Bots hold **long-lived WebSockets**. That combination — not the language — dictates the host:

- **Exactly one always-on instance.** A second instance would hold *separate* in-memory games and a bot's socket could land on the instance not running its game (the cross-worker Redis bridge that fixes this is ADR-0020 scale-out, not built).
- **No scale-to-zero** — idle scale-down kills live games and drops sockets.
- **First-class long-lived WebSockets** — rules out request/response function platforms.
- A **redeploy/restart drops in-progress games** — already an accepted MVP risk (ADR-0020 I3).

## Decision
- **Host: Fly.io**, a **single always-on machine** (`min_machines_running = 1`, `auto_stop_machines = false`, keep `fly scale count 1`). One `uvicorn` process, no `--workers`. Config in [`server/fly.toml`](../../server/fly.toml); image is the existing [`server/Dockerfile`](../../server/Dockerfile) (uv, `--no-dev`, runs `alembic upgrade head` then uvicorn on `:8001`).
- **Database: Neon** managed Postgres (external, not Fly Postgres). Connected via `ER_DATABASE_URL = postgresql+asyncpg://…?ssl=require` (a Fly secret). SQLAlchemy's asyncpg dialect maps `?ssl=require` to asyncpg's `ssl` arg; Neon's `sslmode`/`channel_binding` query keys must be stripped (asyncpg rejects them).
- **Frontend: separate origin + CORS**, not same-origin. The human session is a **stateless Bearer JWT** (ADR-0013 / D-l), which is CORS-friendly with no SameSite/cookie issues; the only cookie (the OAuth CSRF cookie) is same-site to the backend during the redirect. So a separate static host (Cloudflare Pages / Netlify / Fly static) is clean — set `ER_CORS_ALLOW_ORIGINS` to the frontend origin. (The real dashboard is V6; V1's bare view can point at the deployed API meanwhile.)
- **TLS** is provided by Fly, which is also what makes the OAuth `Secure` cookie work in prod (the `ER_OAUTH_COOKIE_SECURE=false` toggle is dev-only).
- **Deploy** is CI-gated: [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) fires on a green CI run on `main`, deploys the validated SHA via `flyctl`, and is **disarmed until** `DEPLOY_ENABLED=true` + `FLY_API_TOKEN` are set.

## Alternatives considered
- **Render / Railway** — equally capable for a single always-on WS service + managed PG; rejected only as default because Fly is the playbook's documented target (least new tooling). A fine flip on preference.
- **Serverless (Cloud Run / Lambda / Vercel functions)** — rejected for the MVP: autoscaling + request lifecycle + scale-to-zero fight the single-process in-memory model, and WS lifetimes map poorly. Revisit only **after** the ADR-0020 Redis-bridge scale-out.
- **Bare VM + `docker compose`** — cheapest/most control; rejected as default for the ops burden (own TLS, restarts, deploy scripting).
- **Fly Managed Postgres / Fly Postgres app** — rejected in favour of Neon per preference; Neon gives branching, generous free tier, and keeps DB state off the compute host. Trade-off: an extra network hop + possible Neon free-tier compute cold-start (~1–2s), absorbed by the health-check grace period and irrelevant at finalization latency.

## Consequences
- **Positive:** fits the single-worker constraint exactly; TLS + WS out of the box; Bearer-JWT means cross-origin frontend is painless; a clean, non-dead-end scale path (Fly + Upstash Redis + more machines when ADR-0020 lands); a few $/month.
- **Negative / costs:** deliberately no HA/redundancy — a machine restart or deploy drops in-progress games (I3, accepted); Neon cold-start on the free tier; **K4 (target concurrency) still open** — the smallest VM covers the MVP's handful of games, but pin a number before a real launch to size up.
- **Follow-ons:** frontend deployment target + its API base URL (V6); revisit HA + the Redis-bridge when concurrency demands it; a `deploy.yml` staging environment if/when useful.
