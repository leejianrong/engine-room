---
shaping: true
---

# Engine Room MVP — Slices

Implementation plan for the selected shape. Ground truth for slice definitions and per-slice breadboards. Higher level: [shaping.md](shaping.md) (R's, Shape A, fit check). Lower level: individual `V<n>-plan.md` files (created when a slice is picked up).

**Selected shape:** A (walking skeleton, then thicken) — see [shaping.md](shaping.md#decision).
Shape A's parts A1…A7 map one-to-one to vertical slices V1…V7, each ending in a demo.

**Breadboard depth policy (decided 2026-07-08):** V1 is fully breadboarded below. V2–V7 are defined at slice level (goal / demo / thickens / est. R-coverage) and breadboarded **just-in-time** when picked up — later slices thicken named V1 affordances (no new subsystems), and detailing them now would drift out of sync before it's load-bearing. Spike any ⚠️ that surfaces during a slice's plan rather than breadboarding blind now.

---

## Slice map

| Slice | From part | Goal (the demo) | Thickens |
|-------|-----------|-----------------|----------|
| **V1** ✅ | A1 | Stub-auth bot ↔ house `RandomBot` plays a full real 3+0 game under the server clock; moves stream live to a SvelteKit page; result+PGN in Postgres | — (skeleton) |
| **V2** ✅ | A2 | Sign in with GitHub, create a bot, get a key once; the **real key** authenticates the WS handshake (stub-auth removed) | N1 auth; +REST bot-CRUD; newest-wins |
| **V3** ✅ | A3 | Two real user bots get matched by Elo in a 3+0 pool; same-owner bots never paired; a lonely seek expires | N3 matcher → pools |
| **V4** ✅ | A4 | A bot killed mid-game reconnects and resumes the same seat; blind move-resend is safe; both-gone game aborts | N1/N5 resilience |
| **V5** | A5 | Bots resign and agree draws; server auto-draws stalemate/insufficient/repetition; ratings move on FINISHED | N5/N8 outcomes |
| **V6** | A6 | Anonymous visitor opens the dashboard, sees the live lobby, clicks a game, watches from the correct current state, replays from move 1 | N9/U1 spectator UX |
| **V7** | A7 | A newcomer `pip`-installs `chessroom`, runs the `uv` quickstart `RandomBot`, and is playing in minutes; UCI bridge points an engine at the platform | client → packaged SDK |

**End-to-end smoke test** (PRD Testing Decisions) becomes meaningful once V2+V6+V7 exist (real signup → SDK run → watch on dashboard); it is authored against the demoable slice at that point.

---

## V1 — Skeleton thread

**Status:** ✅ **complete** (2026-07-08). Built in 8 sub-steps (see `V1-plan.md`); the walking skeleton runs end-to-end: connect → seek → pair vs house → play under the server clock → stream to spectators via SSE → render live in a SvelteKit page → persist to Postgres. 29 tests pass (primary WS seam + pubsub/SSE + live-server e2e + Postgres finalization). Ports: backend :8001, frontend :5174; frontend↔backend via CORS.

### Demo (definition of done for the slice)
Run the server. Run a stub bot-client script. Observe: it connects, seeks 3+0, is paired with the in-process house `RandomBot`, and a full legal game plays out to a natural terminal (checkmate/stalemate) or a **timeout** if a side runs out of clock. A bare web page shows each move appear live. When the game ends, a `games` row exists in Postgres with the result, termination reason, final FEN, and full PGN.

### In scope
- Real WebSocket endpoint `/api/bot/v1`; `hello`/`welcome`/`seek`/`seek_ack`/`game_start`/`your_turn`/`move`/`move_ack`/`game_over` (the happy-path subset of PROTOCOL.md).
- Real `python-chess` board: legality, terminal detection, UCI moves, full FEN each `your_turn`, PGN render.
- Real server-authoritative clock for 3+0: per-seat remaining ms, runs `your_turn`-send → `move`-receive, flags at 0 → timeout loss.
- In-process house `RandomBot` (uniform random legal move).
- Trivial always-pair matcher behind the `MatchmakingQueue` interface.
- In-process `PubSub` behind its interface; SSE endpoint streaming move/`game_over` events.
- 🟡 Minimal **SvelteKit** page consuming the SSE stream (real frontend project stood up now; V6 extends it — decided in [V1-plan D-b](V1-plan.md#build-time-decisions-pinned-for-v1)).
- 🟡 Atomic finalization: one Postgres txn writing the `games` record via **SQLAlchemy 2.0 async + Alembic** (decided in [V1-plan D-a](V1-plan.md#build-time-decisions-pinned-for-v1)).

### Explicitly out (proven by later slices)
Auth (dev-token stub only) → V2 · Elo/pools/TTL/same-owner → V3 · reconnect/`ply`-idempotency/heartbeat/illegal-move-forfeit → V4 · resign/draw/auto-draw/real-Elo → V5 · catch-up snapshot/replay/lobby/board-styling → V6 · packaged SDK/quickstart/UCI bridge → V7 · 5+0 pool (V1 hardcodes 3+0).
🟡 Note: the SvelteKit *project* lands in V1 (D-b), but only the bare move-list view — the styled board, lobby, catch-up and replay are still V6.

### V1 breadboard
The affordance tables + wiring for V1 are in [shaping.md → Detail A → A1](shaping.md#a1--skeleton-thread--v1) (U1–U2, N1–N10). Reproduced-by-reference here to avoid drift; V1-plan.md will cite specific affordance IDs.

### V1 tests (primary WS seam, per PRD)
Driven by an in-process fake protocol client (not the SDK):
- Happy path: connect → seek → `game_start` → `your_turn`/`move` loop → `game_over` with a real result + non-empty PGN.
- Clock/flag: a client that never answers `your_turn` flags; result is `timeout` for the correct color; opponent credited the win.
- Legality: house `RandomBot` only ever produces legal moves; an out-of-turn or malformed frame from the fake client is handled without crashing the game (full forfeit semantics deferred to V4).
- Finalization: on terminal, exactly one `games` row is written with matching result/termination/FEN/PGN.

### Open items carried into V1-plan
- **K3 (hosting) / K4 (concurrency)** remain open (PRD) — V1 assumes a single local process; does not decide deployment.
- Exact clock start instant (server-send vs socket-flush) — PROTOCOL says send-instant; V1-plan pins the monotonic source as an impl detail.
- `games` table minimal column set — finalized in V1-plan (extended by V2 for owner/bot FKs, V5 for rating deltas).

---

## V2 — Real identity

**Status:** ✅ **complete** (2026-07-08). Built in 6 sub-steps (the frontend sub-step dropped —
V2 ships the REST + OAuth backend only, UI stays in V6); see [V2-plan.md](V2-plan.md). Thickens
N1 (handshake auth): stub dev-token → GitHub OAuth (FastAPI-Users, stateless JWT/Bearer) + real
per-bot API keys (`crbk_`, HMAC-SHA256-hashed, shown once, rotatable). Adds the human/management
REST surface (`/api/auth/github`, `/api/users`, `/api/bots`) with a 5-bots/user cap, newest-wins
session replacement (ADR-0016 A6), rotation-terminates-live-session (ADR-0014), and `games`
`white_bot_id`/`black_bot_id` FKs (Alembic `0002`, house bot seeded). 41 unit + 17 integration
tests pass. Matchmaking is still always-pair vs house (V3).

## V3 — Real matchmaking

**Status:** ✅ **complete** (2026-07-09). Built in 6 sub-steps (see [V3-plan.md](V3-plan.md)) on
`feat/v3-matchmaking`. Replaces `AlwaysPairQueue` (N3) with an **Elo widening-window matcher**
behind the same `MatchmakingQueue` interface (R6): per-time-control pools (**3+0 and 5+0**), pair
at ≥2 eligible, closest-rating with a window that starts ±100 and widens +100/10s (uncapped after
60s), **same-owner exclusion** (H5; house exempt), **soft anti-rematch** (E5), seek **TTL 120s** →
`seek_ended{expired}`, `seek_cancel` → `seek_ended{cancelled}`, and a start-grace **reap** of a
ticket whose session vanished before pairing (E7 no-show). `game_start` is now **asynchronous** — a
background matcher loop pairs tickets and delivers it via an injected `GameLauncher` (a change from
V1/V2's synchronous always-pair, ADR-0025). A lone 3+0 seeker gets an **on-demand greeter** house
game (Kind-2 house, ADR-0022); **ambient pool-resident house bots** (Kind-1, house-vs-house for a
never-empty lobby) are designed but deferred to **V6** with the lobby they feed (ADR-0022 addendum).
Ratings are **read-only** (rating updates on FINISHED are V5, ADR-0011). No schema change. Matcher
logic is unit-tested DB-free (injectable clock → deterministic widening/TTL) and the WS seam by a
live-uvicorn two-bot integration test. All checks green.

## V4 — Resilience

**Status:** ✅ **complete** (2026-07-09). Built in 6 sub-steps (see [V4-plan.md](V4-plan.md)) on
`feat/v4-resilience`; the three load-bearing decisions (D-i seat-owned inbox, D-iii per-connection
ping task, D-vi minimal terminal stash) were confirmed by the owner and are pinned. Thickens **N1**
(session/handshake) and **N5** (game loop/seat): a mid-game bot **reconnects with the same key and
resumes the same seat** — `welcome.active_game` carries the §8 snapshot, the seat (which now owns a
**durable inbound queue** that survives a newest-wins session swap, ADR-0009/D-i) is rebound to the
new session, and `your_turn` is re-sent if it's the bot's move; the **clock keeps running while away**
(ADR-0025 #3 — no reconnect window, superseding ADR-0004). `ply`-**idempotency** (PROTOCOL §9): a dup
resend at an applied ply is re-acked (never re-applied), a stale conflicting resend is ignored (not
penalized), a future ply is `INVALID_PLY`. An **illegal/unparseable move on your turn is an instant
forfeit** (`game_over` `illegal_move`, ADR-0016 B7) — flipping V1's report-and-ignore. A
per-connection **heartbeat** (ping/pong, §10, `ER_HB_*` 10s/30s) closes a half-dead socket, and
**mutual abandonment** (both seats gone) **aborts** the game (`ABORTED`, no result/rating, ADR-0010/
0016 I7); a single disconnected bot is never forfeited by heartbeat — only by its clock. A `game_over`
missed while disconnected is delivered on reconnect (D-vi). `GameRegistry` gains a bot→active-game
index; `Game` carries a `LiveState`. **No schema change** (resilience is in-memory). Unit tests cover
idempotency/forfeit + the resume snapshot/index DB-free; live-uvicorn integration tests kill a socket
mid-game and assert resume + finish, safe blind-resend, mutual-abandonment abort, and heartbeat close.
The demo bot (`make demo`) answers pings and reconnects+resumes; `--drop-after N` shows the kill/
reconnect/finish live. All checks green.

## V5–V7 — defined, breadboard deferred

Each is a real vertical slice ending in a demo (see slice map). Full affordance breadboards are produced in this doc when the slice is picked up, and its `V<n>-plan.md` follows. Coarse thickening targets are in [shaping.md → A2–A7](shaping.md#a2a7--thickening-breadboarded-per-slice-in-the-slices-doc).
