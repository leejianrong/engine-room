# Workflow adoption — status

Tracks how much of [DEVELOPER-WORKFLOWS.md](DEVELOPER-WORKFLOWS.md) (the portable playbook)
engine-room has adopted. **Phases A–C are done; Phase D is deferred.**

## Adopted (Phases A–C, 2026-07-08)

| Playbook item | Here |
|---------------|------|
| **CLAUDE.md** agent brief (§7) | [`/CLAUDE.md`](../CLAUDE.md) — build-status table, exact commands, ports, conventions, docs map. |
| **ruff** lint + import sort (§2) | `[tool.ruff]` in `server/pyproject.toml` (`E,F,I`, line 100, excludes `alembic/versions`); a dev dep. Whole tree clean. |
| **Layered tests** (§1) | `server/tests/unit/` (no infra — in-process ASGI TestClient, or a real-uvicorn thread with no DB) vs `server/tests/integration/` (needs Docker). Shared WS test seam in `server/tests/support/fake_client.py`. `pythonpath=["tests"]`. |
| **Testcontainers** (§1a) | `server/tests/integration/conftest.py` spins ephemeral `postgres:16` and exposes an async `session_factory`; the finalize test is now self-contained (no skip, no hand-managed DB). Non-autouse, so the real-server SSE test stays Docker-free. |
| **Pre-push hook** (§3) | `scripts/git-hooks/pre-push` runs `ruff` + `pytest tests/unit` + `npm run check`. Install once: `ln -sf ../../scripts/git-hooks/pre-push .git/hooks/pre-push`. |
| **CI** (§4) | `.github/workflows/ci.yml` — parallel `lint` / `unit` / `integration` / `frontend` jobs on every PR + push to `main`; `uv run --frozen`, `npm ci`, dep caching. |

Test counts today: **27 unit + 2 integration = 29**, ruff clean.

## Deferred to Phase D

| Item | Why not yet | Trigger to do it |
|------|-------------|------------------|
| **Playwright browser e2e** (§1b) | Heaviest item; the live-server SSE test already covers the data path end-to-end. The gap is pixel-level DOM rendering. | After V2, or when a UI regression needs guarding. |
| **Branch-per-slice + PR-only + protected `main`** (§6) | V1 was bootstrapped with small commits straight to `main`. | Adopt starting **V2** — `feat/v2-identity` branch, PR, CI-green-to-merge, branch-protection rule. |
| **Deploy gated on CI** (§5) | Hosting target is undecided — **QUESTIONS.md K3** is still open. The playbook deploys to Fly.io; we haven't chosen. | When K3 is decided. |

## Deliberate divergences from the playbook

- **CORS, not a Vite dev proxy.** The playbook uses a proxy for zero-CORS dev/prod parity; we
  enable CORS on the backend (`config.py` `cors_allow_origins`) so the frontend can call the API
  cross-origin. Revisit at deploy time when the production topology (reverse proxy vs. separate
  origins) is known.
- **Ports** moved off defaults: backend **:8001**, frontend **:5174**, Postgres **:5433**.
- **`create_all` (not alembic) in the integration fixture.** Simpler given the config singleton;
  a future refinement is running real migrations in the fixture (also exercises the migrations),
  as the playbook's §1a does.
