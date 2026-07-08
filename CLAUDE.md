# CLAUDE.md — agent brief for engine-room

Real-time matchmaking & spectating platform for AI chess bots. Bots connect over an
authenticated WebSocket; humans manage bots and spectate. **Trust the code over the docs**
where they disagree, and update the docs.

## Build status (what is / isn't built)

| Area | State |
|------|-------|
| **V1 walking skeleton** | ✅ done — stub-auth bot ↔ house `RandomBot`, server-authoritative clock, `python-chess` rules, live SSE spectating, SvelteKit board, Postgres finalization |
| Real auth (GitHub OAuth, hashed per-bot keys) | ❌ V2 — V1 uses a single stub dev token |
| Elo matchmaking / pools / TTL / same-owner exclusion | ❌ V3 — V1 always-pairs vs the house bot |
| Reconnect, `ply`-idempotency, heartbeat, illegal-move forfeit | ❌ V4 |
| Resign / draw / auto-draw, real Elo updates | ❌ V5 — V1 game_over rating is stubbed |
| Dashboard + lobby + catch-up snapshot + replay | ❌ V6 — V1 view watches one game by `?game=<id>` |
| Packaged `chessroom` SDK + UCI bridge (separate repo) | ❌ V7 — V1's client is `tests/support/fake_client.py` |

Design is fully specified; see **docs/** (below). The build is sliced V1–V7 (Shape A,
walking-skeleton-first) in `docs/shaping/`.

## Stack & layout

- **Backend** — Python + FastAPI + SQLAlchemy 2.0 async + Alembic + Postgres + `python-chess`; `uv`.
- **Frontend** — TypeScript + SvelteKit + Vite (static SPA, SSE-driven).

```
server/      FastAPI app (engine_room/), Alembic, tests/{unit,integration,support}
frontend/    SvelteKit spectator UI
docs/        design/ (REQS, CONTEXT, PRD, PROTOCOL, QUESTIONS), adr/, shaping/
docker-compose.yml   local Postgres on host :5433
```

## Commands

```bash
# once per clone (installs the fast pre-push gate)
ln -sf ../../scripts/git-hooks/pre-push .git/hooks/pre-push

# dev loop
docker compose up -d db                                              # Postgres :5433
cd server   && uv sync && uv run alembic upgrade head
              uv run uvicorn engine_room.app:app --reload --port 8001   # :8001/health
cd frontend && npm install && npm run dev                            # :5174

# checks
cd server   && uv run ruff check . && uv run pytest tests/unit -q    # fast (no Docker)
cd server   && uv run pytest tests/integration -q                    # needs Docker (testcontainers)
cd server   && uv run pytest -q                                      # everything
cd frontend && npm run check                                         # svelte-check
```

**Ports:** backend **:8001**, frontend **:5174**, Postgres **:5433** (all moved off defaults to
avoid collisions). Frontend → backend is **cross-origin via CORS** (see `config.py`
`cors_allow_origins`), not a Vite proxy.

## Testing (layered by cost — see docs/DEVELOPER-WORKFLOWS.md)

- `tests/unit/` — no external infra (in-process ASGI TestClient, or a real uvicorn thread with
  no DB). Fast; runs in the pre-push hook and CI.
- `tests/integration/` — needs Docker: an ephemeral Postgres via **testcontainers**. CI + local-with-Docker.
- Shared helpers (the fake protocol client — the **primary WS test seam**, PRD Option A) live in
  `tests/support/`.
- Playwright browser e2e is **planned (Phase D)**, not yet present.

## Workflow conventions

- **Now (V1 bootstrap):** small, per-sub-step commits directly on `main`, pushed after `pytest`
  is green. Commit messages end with the Co-Authored-By trailer.
- **Planned (from V2 — Phase D, see docs/WORKFLOW-ADOPTION.md):** branch-per-slice off fresh
  `main`, PR-only merges with CI green as the gate, protected `main`, worktrees for parallel work.
- **Pre-push hook** mirrors the fast CI jobs (ruff + `pytest tests/unit` + `npm run check`).
  `git push --no-verify` bypasses it for a one-off.
- Prefer Claude Code `isolation: "worktree"` for parallel file-mutating agent work.

## Docs map

- `docs/README.md` — index. `docs/design/` — REQS, CONTEXT (glossary/domain), PRD, PROTOCOL (wire
  contract), QUESTIONS. `docs/adr/` — 25 decision records. `docs/shaping/` — build plan
  (frame → shaping → slices → V1-plan). `docs/DEVELOPER-WORKFLOWS.md` — the playbook;
  `docs/WORKFLOW-ADOPTION.md` — what we've adopted and what's deferred.
