# CLAUDE.md — agent brief for engine-room

Real-time matchmaking & spectating platform for AI chess bots. Bots connect over an
authenticated WebSocket; humans manage bots and spectate. **Trust the code over the docs**
where they disagree, and update the docs.

## Build status (what is / isn't built)

| Area | State |
|------|-------|
| **V1 walking skeleton** | ✅ done — bot ↔ house `RandomBot`, server-authoritative clock, `python-chess` rules, live SSE spectating, SvelteKit board, Postgres finalization |
| **V2 real identity** | ✅ done — GitHub OAuth (FastAPI-Users, stateless JWT/Bearer), bot CRUD (5/user cap), one rotatable per-bot API key (HMAC-hashed, shown once), real WS-handshake key auth + newest-wins, `games` bot FKs. REST at `/api/auth/github`, `/api/users`, `/api/bots`; backend `auth/` + `bots/` packages |
| **V3 real matchmaking** | ✅ done — Elo widening-window pairing behind `MatchmakingQueue`, 3+0 **and** 5+0 pools, ≥2-to-pair, same-owner exclusion (house exempt), soft anti-rematch, seek TTL→`seek_ended{expired}` + `seek_cancel`, start-grace reap→no-show; **async** `game_start` via a background matcher loop; on-demand **greeter** house game (Kind-2, 3+0) for lone seekers. Ratings **read-only** (updates are V5). Single-process/in-memory |
| **V4 resilience** | ✅ done — reconnect-resume the same seat (`welcome.active_game`, seat-owned durable inbox rebound to the new session, re-sent `your_turn`; clock runs while away — ADR-0025 #3, no reconnect window); `ply`-idempotency (dup re-ack / stale ignore / future INVALID_PLY, PROTOCOL §9); illegal/unparseable move on your turn → **instant forfeit** (`illegal_move`, ADR-0016 B7); heartbeat ping/pong (`ER_HB_*`, 10s/30s) → **mutual-abandonment ABORT** (both seats gone, no result/rating; a lone drop flags on its clock); missed `game_over` delivered on reconnect (D-vi). `GameRegistry` bot→active-game index; `LiveState` on `Game`. No schema change |
| **V5 outcomes & ratings** | ✅ done — `resign`/`draw_offer`/`draw_accept` control messages (§7) route to a per-game control channel the loop always watches (arrive off-turn safely); resign → `resignation` (opponent wins); draw offer surfaced via `your_turn.opponent_draw_offer` (a move implicitly declines, ADR-0016 D6) + `draw_accept` → `agreement`; server **auto-draws** all standard conditions incl. claimable threefold/fifty via `board.outcome(claim_draw=True)` (D8, no claim protocol); **timeout vs insufficient material → DRAW** (D7); **real Elo** (K=32 provisional <30 games / K=16, `ER_ELO_*`) computed + `bots.rating`/`games_played` + per-color `games` rating cols all written in ONE finalize txn (ADR-0025 #5); `game_over.rating` carries real {before,after}; ABORTED still writes no rating. Migration **0003** (first since 0002). House games rate both bots uniformly |
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

**Shortcuts (Makefile):** `make demo` = whole platform + a looping demo bot in Docker (one
command to watch a live game); `make dev` = db + backend + frontend with hot reload, then
`make bot` (another terminal) to start a game; `make mint` prints a real `crbk_` key; `make test`
= fast gate. `make help` lists all targets. The raw steps below are what they wrap.

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

- **Now (from V2 — Phase D adopted):** branch-per-slice off fresh `main` (e.g. `feat/v2-identity`),
  small per-sub-step commits, **PR-only merges with CI green as the gate**. Commit messages end
  with the Co-Authored-By trailer. (Branch **protection** on `main` needs GitHub Pro / a public
  repo — not yet enforced server-side on this private free repo; the discipline is followed by
  convention. See docs/WORKFLOW-ADOPTION.md.)
- **Pre-push hook** mirrors the fast CI jobs (ruff + `pytest tests/unit` + `npm run check`).
  `git push --no-verify` bypasses it for a one-off.
- Prefer Claude Code `isolation: "worktree"` for parallel file-mutating agent work.

## Auth (V2)

- **Humans** sign in with GitHub OAuth → a stateless **JWT** (Bearer) session. Secrets:
  `ER_AUTH_SECRET` (JWT + OAuth state), `ER_GITHUB_OAUTH_CLIENT_ID`/`_SECRET` (empty in dev/CI —
  tests stub the provider). Bot management REST is auth-guarded + owner-scoped. The OAuth CSRF
  cookie is `Secure` (HTTPS) by default; set `ER_OAUTH_COOKIE_SECURE=false` to run the real GitHub
  flow over plain `http://localhost` in dev.
- **Bots** authenticate the WS handshake with a per-bot key `crbk_<43 base62>` in
  `Authorization: Bearer`. Stored only as `HMAC-SHA256(ER_API_KEY_PEPPER, key)`; shown once;
  rotation invalidates instantly + boots the live session (newest-wins). `ER_API_KEY_PEPPER` and
  `ER_AUTH_SECRET` **must** be set in production.

## Docs map

- `docs/README.md` — index. `docs/design/` — REQS, CONTEXT (glossary/domain), PRD, PROTOCOL (wire
  contract), QUESTIONS. `docs/adr/` — 25 decision records. `docs/shaping/` — build plan
  (frame → shaping → slices → V1-plan, V2-plan). `docs/DEVELOPER-WORKFLOWS.md` — the playbook;
  `docs/WORKFLOW-ADOPTION.md` — what we've adopted and what's deferred.
