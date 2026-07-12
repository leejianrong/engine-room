# Workflow adoption — status

Tracks how much of the portable dev-workflow playbook engine-room has adopted. **Phases A–C done; the Phase-D branch/PR flow adopted from V2; Playwright
browser e2e adopted at V6.** Server-enforced branch protection is intentionally skipped (private
repo — see divergences).

## Adopted (Phases A–C, 2026-07-08)

| Playbook item | Here |
|---------------|------|
| **CLAUDE.md** agent brief (§7) | [`/CLAUDE.md`](../CLAUDE.md) — build-status table, exact commands, ports, conventions, docs map. |
| **ruff** lint + import sort (§2) | `[tool.ruff]` in `server/pyproject.toml` (`E,F,I`, line 100, excludes `alembic/versions`); a dev dep. Whole tree clean. |
| **Layered tests** (§1) | `server/tests/unit/` (no infra — in-process ASGI TestClient, or a real-uvicorn thread with no DB) vs `server/tests/integration/` (needs Docker). Shared WS test seam in `server/tests/support/fake_client.py`. `pythonpath=["tests"]`. |
| **Testcontainers** (§1a) | `server/tests/integration/conftest.py` spins ephemeral `postgres:16` and exposes an async `session_factory`; the finalize test is now self-contained (no skip, no hand-managed DB). Non-autouse, so the real-server SSE test stays Docker-free. |
| **Pre-push hook** (§3) | `scripts/git-hooks/pre-push` runs `ruff` + `pytest tests/unit` + `npm run check`. Install once: `ln -sf ../../scripts/git-hooks/pre-push .git/hooks/pre-push`. |
| **CI** (§4) | `.github/workflows/ci.yml` — parallel `lint` / `unit` / `integration` / `frontend` jobs on every PR + push to `main`; `uv run --frozen`, `npm ci`, dep caching. |

Test counts today: **41 unit + 17 integration = 58**, ruff clean (V2).

## Adopted at V2 (Phase D — branch/PR flow)

| Playbook item | Here |
|---------------|------|
| **Branch-per-slice + PR-only merges** (§6) | V2 built on `feat/v2-identity`, small per-sub-step commits, opened as **PR #1**; CI gates the merge. This is the standing convention from V2 on (CLAUDE.md "Workflow conventions"). |

## Adopted at V6 (Phase D — browser e2e)

| Playbook item | Here |
|---------------|------|
| **Playwright browser e2e** (§1b) | `frontend/playwright.config.ts` (`webServer` starts the backend + built preview) + `frontend/e2e/smoke.spec.ts` (the ADR-0023 demo path: dashboard → watch a live ambient game → replay to move 1). `make e2e` locally; CI `e2e` job with a Postgres **service container** + a cached Chromium. One smoke for now — a broader suite (owner flows, error paths) is later. |

## Deferred to Phase D

| Item | Why not yet | Trigger to do it |
|------|-------------|------------------|
| **Real migrations in the integration fixture** (§1a) | The `session_factory` fixture builds the schema with `create_all`, not the Alembic chain; the migration SQL is validated separately by `test_v2_migrations` on a fresh container. **Revisit: switch the fixture to `alembic upgrade head`** so every integration test also exercises the migrations (and drift can't hide). | Do it when convenient; the env.py `sqlalchemy.url` hook already added for the migration test makes this straightforward. |

## Deliberate divergences from the playbook

- **CORS, not a Vite dev proxy.** The playbook uses a proxy for zero-CORS dev/prod parity; we
  enable CORS on the backend (`config.py` `cors_allow_origins`) so the frontend can call the API
  cross-origin. Revisit at deploy time when the production topology (reverse proxy vs. separate
  origins) is known.
- **Ports** moved off defaults: backend **:8001**, frontend **:5174**, Postgres **:5433**.
- **`create_all` (not alembic) in the integration fixture.** Simpler given the config singleton.
  Tracked as a Phase-D revisit above (switch to real migrations); `test_v2_migrations` covers the
  Alembic chain on a fresh container in the meantime.
- **No server-enforced branch protection on `main`** — the repo is deliberately **private** and
  GitHub gates branch-protection rules behind Pro/public (403). The branch-per-slice + PR-only +
  CI-green flow is followed **by convention** (CLAUDE.md "Workflow conventions"); not revisiting
  unless the repo goes public.
