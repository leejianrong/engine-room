Paste the block below into a fresh Claude Code session at the repo root to start V2.
(It's a prompt, not a doc — the "----" lines just mark where it begins/ends.)

------------------------------------------------------------------------------

We're building **engine-room**, a real-time matchmaking + spectating platform for AI
chess bots. **V1 (the walking skeleton) is done and works end-to-end.** I want to build
**V2 — real identity** now.

**First, orient yourself — read these before writing anything:**
- `CLAUDE.md` (repo brief: build status, commands, ports, conventions)
- `docs/shaping/slices.md` (the V1–V7 slice map) and `docs/shaping/shaping.md` (Shape A)
- `docs/shaping/V1-plan.md` (the plan/detail format to mirror for V2)
- `docs/design/PROTOCOL.md` §2–3 (handshake + auth) and the ADRs behind V2:
  ADR-0013 (GitHub OAuth via FastAPI-Users), ADR-0014 (per-bot rotatable API keys,
  hashed, sent as `Authorization: Bearer` at the WS handshake), ADR-0016 A6 (newest-wins
  session replacement), ADR-0009 (User→Bot entities).
- `docs/design/PRD.md` user stories 1–14 (identity, bots, credentials).

**What V2 delivers** (Shape A part A2 — see the slices.md "V2" row):
- Human auth: **GitHub OAuth** (FastAPI-Users), modular for other providers later.
- **Bot CRUD** owned by a user; **5 bots/user** cap (ADR-0019).
- **One rotatable API key per bot**, stored hashed, shown once, prefixed token; rotation
  instantly invalidates the old key.
- The bot **WebSocket handshake authenticates the real key** — replacing V1's stub
  dev-token in `server/engine_room/ws/bot_endpoint.py` — and binds the session to the
  real Bot identity. **Newest-wins**: a new authenticated connection replaces the prior
  live session for that bot.
- REST management API for the above. `games` gains `white_bot_id`/`black_bot_id` FKs
  (Alembic `0002`), replacing V1's `white_name`/`black_name` text columns.

**How to proceed (important — mirror how V1 was built):**
1. **Adopt the branch/PR flow now** (Phase D item — see `docs/WORKFLOW-ADOPTION.md`):
   work on `feat/v2-identity`, open a PR, let CI gate the merge, protect `main`. Do NOT
   commit straight to `main` anymore.
2. **Write `docs/shaping/V2-plan.md` first** (same shape as `V1-plan.md`: build-time
   decisions, affordance→module map, schema + migration, ordered sub-steps each ending in
   a demoable/testable checkpoint, tests at the seams). **Ask me to confirm the open
   decisions before implementing** — at least: how OAuth is exercised in tests (stub the
   provider), whether V2 includes a frontend login/bot-management UI or just the REST API +
   the existing demo flow, the API-key format/prefix + hashing choice, and the
   FastAPI-Users session/token store.
3. Then implement **sub-step by sub-step**, committing per sub-step, running the fast gate
   (`cd server && uv run ruff check . && uv run pytest tests/unit -q && cd ../frontend &&
   npm run check`) before each push.

**Reuse the existing patterns, don't reinvent:**
- `create_app(...)` dependency injection + `app.state` (the finalizer is injected this way;
  do the same for auth/session deps so tests stay fast).
- Layered tests: `server/tests/unit/` (no infra) + `server/tests/integration/`
  (testcontainers Postgres — see `tests/integration/conftest.py`). New User/Bot/key
  persistence + REST auth belong in integration; the WS-seam handshake tests stay in unit
  via `tests/support/fake_client.py` (teach it to send a real key).
- Keep MVP scope: single process, no Redis, Blitz only. Ports: backend :8001, frontend
  :5174, Postgres :5433. Frontend↔backend is CORS (not a proxy).

Start by reading the docs above, then draft `docs/shaping/V2-plan.md` and ask me the open
questions.

------------------------------------------------------------------------------
