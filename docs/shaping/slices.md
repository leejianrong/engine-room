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
| **V2** | A2 | Sign in with GitHub, create a bot, get a key once; the **real key** authenticates the WS handshake (stub-auth removed) | N1 auth; +REST bot-CRUD; newest-wins |
| **V3** | A3 | Two real user bots get matched by Elo in a 3+0 pool; same-owner bots never paired; a lonely seek expires | N3 matcher → pools |
| **V4** | A4 | A bot killed mid-game reconnects and resumes the same seat; blind move-resend is safe; both-gone game aborts | N1/N5 resilience |
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

## V2–V7 — defined, breadboard deferred

Each is a real vertical slice ending in a demo (see slice map). Full affordance breadboards are produced in this doc when the slice is picked up, and its `V<n>-plan.md` follows. Coarse thickening targets are in [shaping.md → A2–A7](shaping.md#a2a7--thickening-breadboarded-per-slice-in-the-slices-doc).
