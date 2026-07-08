Paste the block below into a fresh Claude Code session at the repo root to start V3.
(It's a prompt, not a doc — the "----" lines just mark where it begins/ends.)

------------------------------------------------------------------------------

We're building **engine-room**, a real-time matchmaking + spectating platform for AI chess bots.
**V1 (walking skeleton) and V2 (real identity) are done, merged to `main`, and deployed** (Fly.io
`engine-room` in `sin` + Neon Postgres; `https://engine-room.fly.dev`). I want to build
**V3 — real matchmaking** now.

**First, orient yourself — read these before writing anything:**
- `CLAUDE.md` (repo brief: build status, commands, ports, conventions, Auth section)
- `docs/shaping/slices.md` (the V3 row + the V2 completion note) and `docs/shaping/shaping.md`
  (Shape A, esp. the A3 thickening row)
- `docs/shaping/V1-plan.md` and `docs/shaping/V2-plan.md` (the plan/detail format to mirror)
- The ADRs behind V3: **ADR-0011** (Elo & ratings), **ADR-0012** (matchmaking pool & queue
  policy), **ADR-0016** E8 (the MVP matchmaking numbers), E5 (soft anti-rematch), H5 (same-owner
  exclusion), E7 (start-grace→ABORTED); **ADR-0010** (lifecycle), **ADR-0022** (house bots),
  **ADR-0025** (seek-over-WS).
- `docs/design/PROTOCOL.md` §5 (`seek`/`seek_ack`/`seek_cancel`/`seek_ended`/`game_start`) and
  `docs/design/PRD.md` user stories 28–35.
- **Trust the code over the docs** — read the current `server/engine_room/matchmaking/queue.py`
  (`AlwaysPairQueue`), `ws/bot_endpoint.py` (seek handling), `game/game.py`, `game/registry.py`,
  and the house-bot seed (`persistence/seed.py`, `game/house_bots.py`) before planning; update
  docs where they drift.

**What V3 delivers** (Shape A part A3 — the slices.md "V3" row):
- Replace `AlwaysPairQueue` with **real Elo pools per time control** behind the existing
  `MatchmakingQueue` interface (R6) — **add the 5+0 pool** alongside 3+0 (V1/V2 hardcoded 3+0).
- **Elo-proximity pairing** with a widening rating window; **≥2-to-pair**; **same-owner
  exclusion** (house exempt, ADR-0016 H5); **soft anti-rematch** (ADR-0016 E5); **seek TTL →
  expiry** (`seek_ended {reason:"expired"}`) and **`seek_cancel`** (ADR-0016 E8); **start-grace →
  ABORTED** on no-show (E7).
- Demo: two real user bots get matched by Elo in a 3+0 pool; same-owner bots are never paired;
  a lonely seek expires.

**Important scope note:** V3 does **Elo-based *pairing*** using each bot's rating (bots already
default to 1200 from V2). Actual **rating *updates* on FINISHED games stay in V5** (ADR-0011/A5) —
don't pull them forward.

**How to proceed (mirror V1/V2):**
1. Work on a new branch **`feat/v3-matchmaking`**, open a PR, let CI gate the merge (branch/PR
   flow is the norm from V2; `main` isn't server-side-protected — private repo — so follow it by
   convention).
2. **Write `docs/shaping/V3-plan.md` first** (same shape as V2-plan: build-time decisions,
   affordance→module map, any schema/migration, ordered sub-steps each ending in a
   demoable/testable checkpoint, tests at the seams). **Ask me to confirm the open decisions
   before implementing** — at least:
   - **House-bot presence model** (this shapes the "lonely seek expires" demo): are house bots
     *always seeking* in each pool (so a lone human always gets an instant game, and TTL only
     triggers in edge cases), *fallback* to a house game after a short solo wait, or *strict Elo*
     with the house bot as just one pool member?
   - **Matcher architecture:** a background matcher task/loop (asyncio) vs pair-on-seek; the
     pairing must stay behind `MatchmakingQueue` so a Redis impl can swap in later (R6). Note this
     makes `game_start` **asynchronous** (seek → `seek_ack` now, `game_start` later) — a change
     from V1/V2's synchronous always-pair.
   - **Which E8 numbers to pin now vs defer** (K-factor is V5; window start/widen schedule, seek
     TTL, start-grace) and confirm ratings are read-only in V3.
   - **How the pairing is exercised at the WS seam:** two in-process fake clients seeking on one
     app vs the live-uvicorn harness; how anti-rematch/same-owner state is tracked (in-memory,
     single process).
3. Then implement **sub-step by sub-step**, committing per sub-step and running the fast gate
   before each push:
   `cd server && uv run ruff check . && uv run pytest tests/unit -q && cd ../frontend && npm run check`

**Reuse existing patterns, don't reinvent:** the `MatchmakingQueue` Protocol + `create_app(...)`/
`app.state` dependency injection; layered tests (`tests/unit/` DB-free via
`tests/support/fake_client.py`; `tests/integration/` testcontainers Postgres); the
`FakeBotAuthenticator`/multi-bot test helpers added in V2. Keep MVP scope: single process, no
Redis, Blitz only (3+0 and 5+0). Ports: backend :8001, frontend :5174, Postgres :5433.
Frontend↔backend is CORS.

Start by reading the docs + current matchmaking code, then draft `docs/shaping/V3-plan.md` and
ask me the open decisions.

------------------------------------------------------------------------------
