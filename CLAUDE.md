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
| **V6 spectator UX** | ✅ done — anonymous lobby `GET /api/games` (active from the in-memory registry + last-20 finished from Postgres) polled by a SvelteKit dashboard; **catch-up snapshot** as the first SSE event (`Game.spectator_snapshot()` from `LiveState`, subscribe-before-read; client dedups the join move by `ply`); **replay from move 1** over one uniform `[{ply,san,uci,fen}]` list — live from `LiveState.moves`, finished from the stored PGN via `GET /api/games/{id}`; **styled board** (`lib/Board.svelte`) + watch route (`/watch?game=`) with live-follow/scrub replay controls; **rating change on the SSE `game_over`** (Q6); **ambient Kind-1 house-vs-house bots** (`AmbientSupervisor`) keep the lobby never-empty — **rated + persisted** via the normal launcher, respawn on finish, evicted from the registry when done; row-locked finalizer (`with_for_update`) under concurrent ambient finalize. **Spectator-gated (KAN-209):** a `Presence` last-seen signal (`spectate/presence.py`) bumped by any `GET /api/games` poll OR watch-SSE connect gates the feeder — new games launch only while presence is fresh (`ER_AMBIENT_PRESENCE_WINDOW_SECONDS`, default 60s), it stops refilling (letting in-flight games finish, never aborting) once presence goes stale, and a poll loop (`ER_AMBIENT_PRESENCE_POLL_SECONDS`) cold-starts the lobby when a watcher returns → zero idle-lobby compute/Neon growth; supersedes the blunt `ER_AMBIENT_GAMES=0` manual pause (that knob still works). Migration **0004** (data-only house-bot seed). Playwright smoke e2e (dashboard→watch→replay) adopted (Phase D) |
| **Post-MVP: house-bot personas** | ✅ done — split the shared house identity into two personas (`game/house_bots.py`): the **ephemeral greeter** is `ephraim-bot` (`RandomBot`, easy/one-off, its rating drift ignored); the **permanent ambient** residents are `jian-bot-001` / `jian-bot-002` (`MinimaxBot` — depth-`ER_AMBIENT_MINIMAX_DEPTH`, default 3 — so lobby games look like real chess). Migration **0005** seeds `ephraim-bot` + renames the two ambient rows (IDs kept for FK/history). Still in-process (out-of-process house-bot runners deferred) |
| **V7 hero onboarding** | ✅ done — packaged **`engineroom` SDK** (`sdk/engineroom`, own `uv`/pyproject, **zero `engine_room` imports** — decoupled by the wire contract, ADR-0021, AST-boundary-tested): subclass `Bot` + implement `choose_move(board)`, call `run()`; the run loop (extracted from `devtools/demo_bot`) hides the whole protocol — handshake, auto-seek, `your_turn`→`move`→`move_ack`, heartbeat pong (§10), `ply`-idempotent resend (§9), reconnect-resume (§8); `choose_move` may return `RESIGN`/`ACCEPT_DRAW` (§7). Reference bots `RandomBot`/`MinimaxBot` (mirror the house bots' logic, not shared-imported); **UCI bridge** `UCIBot` + `engineroom-uci` console script (points Stockfish at the platform, client-side). **`uv` quickstart template** (`sdk/quickstart`: `random_bot.py` + `.env.example` + README + optional Dockerfile) — `git clone → uv sync → paste key → uv run → playing`; `make sdk-bot` runs it. Config via `ENGINEROOM_KEY`/`ENGINEROOM_URL` (legacy `CHESSROOM_*` still accepted as a deprecated fallback, KAN-71). Tests: SDK unit over an in-memory fake transport, a live-server contract test (packaged SDK vs the real server, incl. real reconnect + persistence), and an **SDK-fed Playwright e2e** (the ADR-0023 signup→SDK→watch smoke, now real). **Monorepo-package-first**; standalone-repo split + PyPI publish deferred (V7 O-2). No schema change |
| **V8 same-origin + SDK rename** | ✅ done — SPA **served same-origin by uvicorn** (Starlette `StaticFiles` + SPA fallback, `app.py`; **no nginx**), baked into the backend image → a **single Fly app** (`server/fly.toml`, repo-root build context; `fly deploy --config server/fly.toml`; separate frontend app retired) so **CORS is no longer required in prod** (KAN-68/KAN-64); human sessions now ride a **same-origin HttpOnly cookie** `er_session` (`CookieTransport` + stateless `JWTStrategy`, `auth/backend.py`), OAuth callback **302→`/bots`** with the cookie set; SDK **renamed `chessroom`→`engineroom`** (`sdk/engineroom`, `pip install engineroom`, `import engineroom`, `engineroom-uci`) with a PyPI trusted-publishing workflow (`.github/workflows/publish-sdk.yml`, tag `engineroom-v*`) — KAN-69/KAN-70. No schema change |

Design is fully specified; see **docs/** (below). The build is sliced V1–V7 (Shape A,
walking-skeleton-first) in `docs/shaping/`; V8 is a post-MVP topology/rename wave (KAN-68/69/70).

## Stack & layout

- **Backend** — Python + FastAPI + SQLAlchemy 2.0 async + Alembic + Postgres + `python-chess`; `uv`.
- **Frontend** — TypeScript + SvelteKit + Vite (static SPA, SSE-driven). **Served same-origin by
  uvicorn** in prod (Starlette `StaticFiles` + SPA fallback in `app.py`, `ER_STATIC_DIR`) — no nginx.
- **Deploy** — a **single Fly app** (`server/fly.toml`); the backend image bakes the built SPA
  (repo-root Docker build context), so deploy from the repo root: `fly deploy --config server/fly.toml`.
  The separate frontend Fly app was retired. See `docs/DEPLOY.md`.

```
server/      FastAPI app (engine_room/) — also serves the built SPA; Alembic, tests/{unit,integration,support}
frontend/    SvelteKit spectator UI (built into the backend image)
sdk/         engineroom/ (packaged Python SDK, decoupled uv project) + quickstart/ (V7)
docs/        design/ (REQS, CONTEXT, PRD, PROTOCOL, QUESTIONS), adr/, shaping/
docker-compose.yml   local Postgres on host :5433
```

## Commands

**Shortcuts (Makefile):** `make demo` = whole platform + a looping demo bot in Docker (one
command to watch a live game); `make dev` = db + backend + frontend with hot reload, then
`make bot` (another terminal) to start a game; `make mint` prints a real `crbk_` key; `make test`
= fast gate; `make down` stops the stack (`make down-clean` also wipes the Postgres volume for a
clean slate). `make help` lists all targets. The raw steps below are what they wrap.

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
avoid collisions). **Same-origin (V8, KAN-68):** in prod the SPA is served by uvicorn itself, so
there's one origin and **CORS is not required**. In dev the Vite server on :5174 **proxies** `/api`,
`/auth`, `/users` to :8001 (`frontend/vite.config.ts`), so dev is same-origin too. The CORS
middleware + `config.py cors_allow_origins` are kept (harmless) only for hosting the SPA elsewhere.

## Testing (layered by cost)

- `tests/unit/` — no external infra (in-process ASGI TestClient, or a real uvicorn thread with
  no DB). Fast; runs in the pre-push hook and CI.
- `tests/integration/` — needs Docker: an ephemeral Postgres via **testcontainers**. CI + local-with-Docker.
- Shared helpers (the fake protocol client — the **primary WS test seam**, PRD Option A) live in
  `tests/support/`.
- Playwright browser e2e landed in **V6** (`frontend/e2e/`, `make e2e` / CI `e2e` job): a
  smoke test (dashboard → watch → replay) that Playwright drives against a self-started
  backend+frontend (DB must be up + migrated). Phase D adopted. **V7** adds `e2e/sdk.spec.ts` — the
  ADR-0023 flow (mint a key → run the SDK's quickstart bot → watch it on the dashboard).
- `sdk/engineroom/tests/` — the **SDK's own** fast unit tests (no infra): the run loop over an
  in-memory fake transport + an import-boundary check. Its own `uv` project → a dedicated CI `sdk`
  job + pre-push line; `make test` runs it too. The packaged SDK is *also* run against the real
  server in `server/tests/integration/test_v7_sdk_live.py` (the contract test, needs Docker).

## Workflow conventions

- **Now (from V2 — Phase D adopted):** branch-per-slice off fresh `main` (e.g. `feat/v2-identity`),
  small per-sub-step commits, **PR-only merges with CI green as the gate**. Commit messages end
  with the Co-Authored-By trailer. (Branch **protection** on `main` needs GitHub Pro / a public
  repo — not yet enforced server-side on this private free repo; the discipline is followed by
  convention. See docs/WORKFLOW-ADOPTION.md.)
- **Land policy — merge on green CI.** A PR may be merged once **all CI checks are green** (the
  6 `ci.yml` jobs — lint, unit, sdk, integration, frontend, e2e — plus the `gitleaks` scan, and the
  docs `build` check on docs PRs) and the diff has been reviewed. Use a **merge commit**
  (`gh pr merge <n> --merge --delete-branch`), not squash. Don't merge on red or pending; a card
  with a DB migration lands alone (+ prod-verify once prod exists). This applies to Dependabot PRs
  too — green CI + a diff review is the bar.
- **Pre-push hook** mirrors the fast CI jobs (ruff + `pytest tests/unit` + `npm run check`).
  `git push --no-verify` bypasses it for a one-off.
- Prefer Claude Code `isolation: "worktree"` for parallel file-mutating agent work.

## Auth (V2, cookie topology V8)

- **Humans** sign in with GitHub OAuth → a **same-origin HttpOnly cookie** `er_session`
  (`CookieTransport` + a stateless `JWTStrategy`, `auth/backend.py`; the token is still a stateless
  JWT — no session table, MVP R5). The browser sends it automatically same-origin (KAN-68), and JS
  can't read it (XSS-hardened). The OAuth callback finishes by **302-redirecting to `/bots`** with the
  cookie set (KAN-64) — login lands the human back in the SPA, not on a raw-JSON page. Secrets:
  `ER_AUTH_SECRET` (JWT + OAuth state), `ER_GITHUB_OAUTH_CLIENT_ID`/`_SECRET` (empty in dev/CI —
  tests stub the provider). Bot management REST is auth-guarded + owner-scoped. Cookies are `Secure`
  (HTTPS) by default; set `ER_OAUTH_COOKIE_SECURE=false` to run over plain `http://localhost` in dev.
- **Bots** authenticate the WS handshake with a per-bot key `crbk_<43 base62>` in
  `Authorization: Bearer`. Stored only as `HMAC-SHA256(ER_API_KEY_PEPPER, key)`; shown once;
  rotation invalidates instantly + boots the live session (newest-wins). `ER_API_KEY_PEPPER` and
  `ER_AUTH_SECRET` **must** be set in production.

## Docs map

- `docs/README.md` — index. `docs/design/` — REQS, CONTEXT (glossary/domain), PRD, PROTOCOL (wire
  contract), QUESTIONS. `docs/adr/` — 25 decision records. `docs/shaping/` — build plan
  (frame → shaping → slices → V1-plan, V2-plan).
  `docs/WORKFLOW-ADOPTION.md` — what we've adopted and what's deferred. `docs/sdk/` — the published
  **SDK guide + tutorial ladder** (random → GreedyBot → minimax → your own engine).
- **Published docs site.** `docs/*.md` is built by **Zensical** (`zensical.toml`, Material theme) and
  deployed to **GitHub Pages** by `.github/workflows/docs.yml` (on push to `main`; that workflow also
  runs a build-only check on PRs) at **https://leejianrong.github.io/engine-room/**. Preview locally
  from the repo root with `zensical build` (or `zensical serve`). The built `site/` dir is **generated
  output — gitignored**, rebuilt fresh in CI (`zensical build --clean`); never commit it.

## Local / generated files (gitignored — not committed)

- **`site/`** — Zensical docs build output (above); regenerate with `zensical build`, don't commit.
- **`.mcp.json`** — machine-local MCP wiring (the Kanban board's `mcp__kanban__*` server + its PAT).
  Holds a credential, so it's gitignored and lives only on the dev machine — never tracked/committed.
- `.claude/worktrees/` (transient agent worktrees) + `.claude/settings.local.json` (local settings).
