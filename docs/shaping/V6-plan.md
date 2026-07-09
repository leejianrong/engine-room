---
shaping: true
---

# V6 Plan — Spectator UX (dashboard + lobby + catch-up + replay)

**Status: ✅ COMPLETE (2026-07-09).** Built in 7 sub-steps on `feat/v6-spectator` off merged V5
(`b5e055b`, PR #12); all six open decisions confirmed up front (§ Decisions confirmed — Q1/Q2/Q3/Q5
as ★, Q4 and Q6 owner-overridden). 15 new unit + 5 new integration tests + a Playwright smoke; full
fast gate + integration suite + e2e green. Ground truth is the ADRs + [PROTOCOL.md](../design/PROTOCOL.md);
where this plan and the docs disagree, **the code wins and the docs get updated** (CLAUDE.md,
slices.md, ADR-0015/0022 updated for V6).

**Deviations as built:** (a) the confirmed Q4 override (rated + persisted ambient) turned "no schema
change" into a **data-only Alembic 0004** seeding `house-random-2`, added `with_for_update` row-locks
to the V5 finalizer (D-g2), and made the `AmbientSupervisor` **evict finished ambient games from the
registry** (unplanned) so `_games` stays bounded under the endless stream. (b) `GameLauncher.launch`
now **returns its run_game task** so the supervisor can refill on game-end; the supervisor uses a
**dedicated ambient launcher** with its own move delay (so ambient pacing is independent of the
greeter's `house_move_delay`). (c) the SSE endpoint **short-circuits a finished-but-in-memory game**
(snapshot + a synthesized `game_over`, then close) so a late SSE join can't hang. (d) the spectator
`snapshot` carries `result`/`termination` (null while live) for that short-circuit. (e) frontend
routing is `/` (lobby) + `/watch?game=<id>` query param (SPA fallback already configured), not a
dynamic `[id]` route. Everything else matches the plan.

Implementation plan for slice **V6** (Shape A, part A6). Higher levels: [slices.md](slices.md) (V6
row), [shaping.md](shaping.md) (R's, Shape A, A6 in the A2–A7 thickening row).

## Goal (definition of done)
> Anonymous visitor opens the dashboard, sees the live lobby, clicks a game, watches from the
> **correct current state**, replays from move 1.

Concretely:
- **Lobby / dashboard** — a REST endpoint lists active (+ recently-finished) games with both bots'
  name+rating, time control, side-to-move/ply, and state; a SvelteKit dashboard **polls** it and
  renders a clickable list of live games.
- **Catch-up snapshot** — a spectator joining a live game mid-stream first receives the **current**
  board state (fen / ply / clocks / move-list-so-far / players) and *then* the live SSE tail, with
  **no lost or missing moves** at the join boundary.
- **Replay from move 1** — step / scrub through a game from the start: for **finished** games from the
  stored PGN, for **live** games from the accumulated move history — one uniform client replay model,
  with playback controls.
- **Real board UI** — a styled board (not a bare glyph grid), both players' name+rating/clock/
  side-to-move, and the **rating change on game_over** (surface V5 ratings in the SSE `game_over`
  event now — V5 Q6).
- **Ambient house bots** (ADR-0022 Kind-1) — a small number of house-vs-house games so the lobby is
  never empty for a first-time visitor; they **respawn** when they finish.

Stays single-process / in-memory for live state (R5). The **only** durable change is a data-only
Alembic `0004` seeding a second house-bot identity (D-h) — **no DDL / no new columns**. No new
game-rules/rating behavior (that was V5); V6 is the view layer + the ambient-bot feeder.

## What thickens (A6 → V6)
Per [shaping.md A2–A7 table](shaping.md#a2a7--thickening-breadboarded-per-slice-in-the-slices-doc):
> N9 gains catch-up snapshot + replay; U1/U2 SvelteKit view (stood up in V1) **extended** with a real
> board + REST-poll lobby.

No new *subsystems*. V6 thickens:
- **N9 (spectator SSE):** the stream now leads with a **catch-up snapshot** built from `game.live`
  before the live tail; the `game_over` event carries the V5 rating change.
- **New read REST surface** on `games` — a lobby list (`GET /api/games`) and a single-game replay/
  detail view (`GET /api/games/{id}`). Read-only, anonymous (ADR-0015 F6), CORS-enabled like SSE.
- **U1/U2 (SvelteKit view):** V1's bare `?game=` page splits into a **lobby route** (poll the list)
  and a **watch route** (catch-up + live tail + replay controls) over a **styled board component**.
- **N4/house (ADR-0022 Kind-1):** a background **ambient supervisor** keeps N house-vs-house games
  live so the lobby is never empty; games respawn on finish.

N1–N3 (handshake/seek/matcher), N5/N6 (loop/clock), N7 (pubsub), N8/N10 (finalize/persistence infra)
are untouched, except: worker publishes the rating on `game_over` (Q6) and appends a SAN move-list to
`LiveState` (the catch-up/replay source).

## The core problem (why this slice is real work)
Three hard points:

1. **Catch-up without a lost-event race.** A spectator joining mid-game must see the *current*
   position **and** every subsequent move, with none dropped in the gap between "read current state"
   and "start streaming". V1's SSE already **subscribes before the first yield** (no lost tail); V6
   must fold the snapshot into that same ordering so a move published *during* the join is never lost
   — accepting that the join move may appear **both** in the snapshot and as the first tail event
   (the client dedups by `ply`, mirroring V4's `ply`-idempotency philosophy).

2. **One replay model over two sources.** A live game's history lives **in memory** (`LiveState`,
   which today keeps `applied` = ply→uci but **no SAN / per-ply FEN**); a finished game's history
   lives **in Postgres as PGN**. Replay-from-move-1 must work identically for both. So both sources
   must project to the **same** ordered `[{ply, san, uci, fen}]` shape the client scrubs over.

3. **A never-empty lobby without disturbing real matchmaking.** ADR-0022 Kind-1 wants house-vs-house
   games *always present*, but they must not crowd real-vs-real pairing (the V3 pool / same-owner /
   anti-rematch invariants) nor pollute ratings or game history. They must be created **outside** the
   matcher pool and **respawn** on finish, cleanly bounded to N.

## Build-time decisions

### Pinned (low-fork; rationale below)
| # | Decision | Rationale |
|---|----------|-----------|
| D-a | **Catch-up = snapshot as the first SSE event** (not a separate REST GET + subscribe). The endpoint subscribes to `game:{id}` (as today), then reads `game.live` and yields a `{"type":"snapshot", …}` event, then streams the tail. | Preserves the existing **subscribe-before-first-yield** race fix (no lost tail). REST-then-subscribe reintroduces a gap. A move landing between subscribe and snapshot-read appears twice → the client ignores tail `move`/`game_over` events with `ply < snapshot.ply` (dedup by ply). |
| D-b | **The snapshot is built by a new `Game.spectator_snapshot()`** (sibling to `resume_payload`), reading `LiveState`. Shape: `{type:"snapshot", game_id, state, white{name,rating}, black{name,rating}, time_control, initial_fen, fen, ply, to_move, last_move, clocks, moves:[{ply,san,uci,fen}], result?, termination?}`. | Single source of truth on the live game (as `resume_payload` already is for reconnect); a spectator needs players + the full move-list-so-far to both render *and* replay. Reuses the same `LiveState` the loop maintains. |
| D-c | **`LiveState` gains `moves: list[dict]` — the live move history** ({ply, uci, san, fen}); the loop appends one entry per applied move (it already computes `san` and `board.fen()` at that point). This is the **live replay source**; the SSE `move` event already carries the same four fields, so snapshot-moves + tail-moves = one uniform list the client accumulates. | The catch-up snapshot and live replay need SAN + per-ply FEN, which `applied` (ply→uci) lacks. Appending in the loop is one line at the spot that already has the data — no reconstruction. |
| D-d | **Replay/detail = `GET /api/games/{id}` returning the uniform game view** for BOTH live and finished games. Source resolution: if the game is in the `GameRegistry` with live state → project from `LiveState`; else → load the `games` row from Postgres and **parse the PGN** (python-chess) into `[{ply,san,uci,fen}]` with `initial_fen = game.board().fen()`. Payload: `{game_id, state, white{name,rating,bot_id}, black{…}, time_control, initial_fen, moves[], result, termination, final_fen, rating:{white:{before,after}, black:{…}}?}`. | One endpoint, one client replay model over two storage backends. Finished games survive a server restart (Postgres); live games (and finished-still-in-memory) come from the registry. The client never needs a chess engine — the server emits per-ply FEN. |
| D-e | **Lobby = `GET /api/games` merging two sources.** Active/paired games from the in-memory `GameRegistry` (a new `list_active()` accessor); recently-finished from Postgres (`ORDER BY finished_at DESC LIMIT N`). Each entry: `{game_id, state, white{name,rating}, black{name,rating}, time_control, ply, to_move, started_at}` (+ `result`/`termination` for finished). Poll interval **3s** (client), cap **N=20** finished. | Active state only exists in memory (ADR-0020); finished games are canonical in Postgres and survive restart (and give a stable `finished_at` ordering). Splitting by state avoids double-listing a just-finished game. Poll (not a lobby SSE) is the ADR-0015 F3 MVP choice — simplest, good-enough for a low-traffic lobby. |
| D-f | **SSE `game_over` carries the rating change (Q6 realized).** The worker publishes `rating: {white:{before,after}, black:{before,after}}` on the `game_over` event when the finalizer returned a `FinalizeResult` (omitted for ABORTED / unrated / DB-free). The bot-facing per-seat `game_over.rating` is unchanged. | V6 is where the lobby/watch UI needs it; the worker already holds the `FinalizeResult`. No new computation — just fan it out to spectators too. |
| D-g | **Ambient house games are created OUTSIDE the matcher but launched through the normal `GameLauncher` (finalizer included) — so they ARE persisted and rated (Q4 confirmed).** A background `AmbientSupervisor` (started in the lifespan) maintains `ER_AMBIENT_GAMES` live house-vs-house games in the 3+0 pool: whenever the live count < N it creates a `Game` with two seeded house identities and calls `launcher.launch(game)` with a watchable move delay; when one finishes it respawns. | Meets the *never-empty-lobby* guarantee (ADR-0022 Kind-1) and matches ADR-0022's main text (house bots "rated normally, occupy the leaderboard"). Reuses the exact real-game launch path (game_start fan-out + persistence + Elo). Created directly (not via a pool ticket) so they never interfere with real pairing / same-owner / anti-rematch. Bounded + self-healing. House rating drift is accepted (O-1). |
| D-g2 | **The finalizer loads each bot `with_for_update()` (row lock) before the SELECT-then-UPDATE rating write.** | Ambient games share the two house identities and finish frequently, so two finalize txns can now touch the same `bots` row concurrently — an un-locked read-modify-write could lose a rating update. A `SELECT … FOR UPDATE` serializes them. Low-risk hardening of the V5 finalizer, made live by D-g. |
| D-h | **A second house identity `house-random-2`** (`bot_house_random_2`, same `RandomBot` mover, rating 1200) is **seeded as a real `bots` row** (Alembic `0004`, data-only) so the ambient games' FKs resolve — mirroring how `0002` seeded `bot_house_random`. | House-vs-*house* needs two distinct `BotInfo` ids; since ambient games are now finalized (D-g), the opponent needs a persistent identity for `games.black_bot_id` FK integrity. |
| D-i | **One data-only migration (Alembic `0004`) — no DDL.** It seeds the `house-random-2` `bots` row (D-h). Lobby finished-list + replay read existing `games`/`bots` columns; the SSE rating comes from the in-flight `FinalizeResult`. | V6 adds no *columns/tables* — only a seed row, following the V2 `0002` house-seed precedent. (`0002`, `0003` stand; `0004` is a seed.) |
| D-j | **Frontend: two SPA routes over a shared styled board component.** `/` = lobby (polls `GET /api/games`, clickable cards of live games incl. ambient); `/watch?game=<id>` = watch (SSE catch-up + live tail for live games; `GET /api/games/{id}` for finished) with **replay controls** (⏮ ◀ ▶ ⏭ + a ply slider + play/pause) scrubbing the accumulated move list. A `lib/Board.svelte` renders a **styled CSS board** (coordinates, light/dark theme, last-move highlight) using unicode glyphs — self-contained, **no external CDN/lib** (ADR-0017 / CSP). `lib/api.ts` centralizes `API_BASE` + fetch/EventSource helpers. | Minimal routing that works with the existing SvelteKit static-SPA setup (`ssr=false`); a query param avoids dynamic-route/prerender fuss (verify adapter `fallback` at impl). Extends V1's view (D-b) rather than replacing it; the glyph board is already legible — V6 styles it properly, keeping an inline SVG piece set as later polish. |
| D-k | **MVP scope held:** single process, no Redis; Blitz only (3+0/5+0); ports :8001/:5174/:5433; frontend↔backend CORS. Spectating stays **anonymous, read-only** (ADR-0015 F6). SDK/UCI stay **V7**. **Bot-management UI is OUT of V6** (kept a later-polish item — the V2 REST exists; a browser UI for create-bot/see-key/list-your-bots is not on the A6 critical path and pulls in auth-in-the-browser). | R5 / ADR-0023 MVP scope; unchanged from V1–V5. Keeps V6 to the spectator thread the slice is named for. |

### Decisions confirmed (2026-07-09)
The owner confirmed Q1/Q2/Q3/Q5 as recommended (★) and **overrode** Q4 and Q6:

| # | Question | Confirmed |
|---|----------|-----------|
| **Q1 Lobby finished-list** | Include recently-finished, and from where? | ★ **Yes — active from the in-memory registry + last 20 finished from Postgres** (D-e). Poll every 3s. |
| **Q2 Catch-up mechanism** | Snapshot-as-first-SSE-event vs REST-then-subscribe? | ★ **Snapshot as the first SSE event** (D-a/D-b); client dedups the join move by `ply`. |
| **Q3 Replay source** | One endpoint for both; add SAN move-list to `LiveState`? | ★ **Yes to both** — `GET /api/games/{id}` projects `LiveState` (live) or parses PGN (finished) into one `[{ply,san,uci,fen}]` shape (D-c/D-d). |
| **Q4 Ambient house bots** | How many/which pools/rated?/respawn/coexistence? | **OVERRIDE (not the ★ unrated option): RATED + PERSISTED.** N=2 house-vs-house in 3+0, respawn on finish, created outside the matcher but launched via the normal finalizer-carrying `GameLauncher` (D-g). Needs a seeded 2nd house identity (D-h, migration `0004`) and a row-locked finalizer (D-g2). House rating drift accepted (O-1). |
| **Q5 SSE `game_over` ratings** | Add the rating change to the spectator `game_over`? | ★ **Yes — add `rating:{white,black:{before,after}}` to the SSE `game_over` event** (D-f). |
| **Q6 Playwright** | Introduce browser e2e now, or defer? | **OVERRIDE (not the ★ defer option): ONE SMOKE E2E NOW.** Add a single Playwright test for dashboard→click→watch→replay (the ADR-0023 end-to-end smoke) + the Playwright/CI setup it needs. Phase D (browser e2e) is thus adopted in V6. |

---

### Catch-up snapshot (D-a/D-b/D-c) — the design
```
GET /api/spectate/{game_id}:
  sub = pubsub.subscribe(game:{id})          # BEFORE any read — no lost tail (V1 fix)
  yield ": connected\n\n"
  snap = game.spectator_snapshot()           # read game.live AFTER subscribing
  if snap: yield data: {type:"snapshot", ...snap}   # players + fen/ply/clocks + moves-so-far
  loop: ev = await sub.get(); yield data: ev; if ev.type=="game_over": return
```
- A `move` (or `game_over`) published in the window between `subscribe` and `spectator_snapshot()`
  is in **both** the snapshot (`moves`/`ply`) and the tail → the **client ignores** tail events with
  `ply < snapshot.ply` (dedup). No move is ever lost; at worst one is delivered twice and dropped.
- If `game.live is None` (a just-created PAIRED game before the loop's first tick) the snapshot is
  omitted and the client falls back to `game_start` from the tail (unchanged V1 behavior).
- **Finished game opened via SSE:** if still in the registry, the snapshot shows the final position +
  full `moves` and the stream ends (no tail); the watch page then enables replay from the snapshot's
  `moves`. If not in the registry (post-restart), SSE 404s → the watch page uses `GET /api/games/{id}`
  (Postgres) instead. The lobby links finished games to `/watch?game=<id>&finished=1` so the page
  goes straight to the REST detail path.

### Replay model (D-c/D-d) — one client list, two server sources
```
LiveState.moves: list[{ply, uci, san, fen}]     # appended in run_game after each board.push
# worker.py, right after `san`/`board.push`/`board.fen()` are computed:
live.moves.append({"ply": ply, "uci": uci, "san": san, "fen": board.fen()})

GET /api/games/{id} -> uniform game view:
  g = registry.get(id)
  if g and g.live: return project_live(g)          # from LiveState (in_progress OR finished-in-mem)
  else:            return project_finished(pg_row) # parse PGN -> [{ply,san,uci,fen}] via python-chess
# client replay state: positions = [initial_fen, *moves.map(m => m.fen)]; index in [0, len-1]
```
The watch page holds one `moves[]` (from SSE snapshot+tail for a live game, or from `GET
/api/games/{id}` for a finished one) and one `viewIndex`. Live-following = viewIndex pinned to the
last move; scrubbing back detaches it (a "▶ live" button re-pins). Same controls, same list, both cases.

### Ambient house bots (D-g/D-h) — the design (rated + persisted, Q4 confirmed)
```
AmbientSupervisor(registry, launcher, house_a, house_b, n=2, tc=3+0, move_delay≈1s):
  started/stopped by the app lifespan (like the matcher loop)
  keeps `n` live house-vs-house games:
    on start and whenever a game ends -> while live_count < n: spawn_one()
    spawn_one():
      game = registry.create_game(white=Participant(house_a, is_house=True, house=<RandomBot a>),
                                   black=Participant(house_b, is_house=True, house=<RandomBot b>), tc)
      await launcher.launch(game)      # normal path: seats + bind + run_game with the real finalizer
      track the returned task; on its completion -> refill
```
- **Not** enrolled in the matcher pool → zero interference with real pairing, same-owner (H5),
  anti-rematch (E5), or the greeter (Kind-2). Created directly, then launched through the *same*
  `GameLauncher` real games use — so they persist to `games` and rate both house bots via the V5
  finalizer (Q3 "rate both uniformly").
- The supervisor watches each launched game's task to refill (the `GameLauncher` already tracks task
  refs; the supervisor adds a done-callback to trigger `_refill`). Because house seats have no
  session, `bind_active`/`unbind_active` are no-ops for them — the games still appear in the lobby's
  **active** list via `list_active()` (registry `_games`, state in {paired,in_progress}) and, once
  finished, in the **finished** list (Postgres).
- Random-vs-random terminates via V5's `claim_draw=True` auto-draw (threefold/fifty) even in long
  games; the ~1s move delay makes them watchable and bounds CPU.
- Two `RandomBot` movers with the two seeded identities (`bot_house_random`, `bot_house_random_2`).
- Config: `ER_AMBIENT_GAMES` (default **2**, `0` disables — CI/unit-tests set 0 for determinism;
  ambient integration tests set 2), `ER_AMBIENT_MOVE_DELAY_SECONDS` (default **1.0**),
  `ER_AMBIENT_POOL` (default `"180+0"`).

## Project layout (changes this slice)
```
server/engine_room/
  game/
    game.py            # + LiveState.moves; + Game.spectator_snapshot(); Game.list-friendly view helper
    worker.py          # append to live.moves each ply; publish rating on the game_over event (Q6/D-f)
    registry.py        # + GameRegistry.list_active() (paired|in_progress games)
    house_bots.py      # + house-random-2 identity constants + RandomBot(id=...) for the 2nd (D-h)
    ambient.py         # NEW — AmbientSupervisor (D-g), started/stopped by the lifespan
  spectate/
    sse.py             # snapshot-as-first-event (D-a); dedup contract documented
    games.py           # NEW — GET /api/games (lobby, D-e) + GET /api/games/{id} (replay/detail, D-d)
  persistence/
    finalize.py        # + with_for_update() row lock on the bot loads (D-g2)
  app.py               # mount games router; start/stop AmbientSupervisor in the lifespan; DI knobs
  config.py            # + ER_AMBIENT_* + ER_LOBBY_* knobs
  alembic/versions/0004_*.py  # NEW — data-only: seed the house-random-2 bots row (D-h)
frontend/src/
  routes/
    +page.svelte       # -> LOBBY: poll GET /api/games, render live-game cards, link to /watch
    watch/+page.svelte # NEW -> WATCH: SSE catch-up + live tail + replay controls (was the old +page)
  lib/
    Board.svelte       # NEW — styled board component (glyphs, coords, last-move highlight, flip)
    ReplayControls.svelte  # NEW — ⏮ ◀ ▶ ⏭ + ply slider + play/pause
    api.ts             # NEW — API_BASE + typed fetch/EventSource helpers + shared types
tests/e2e/           # NEW — Playwright smoke: dashboard -> watch -> replay (Q6); playwright config
# alembic 0004 is data-only (seed row); no models.py column change (D-i)
```

## Affordance → module map
| Affordance | Module | Notes |
|-----------|--------|-------|
| Lobby list (U1, N9) | `spectate/games.py` + `game/registry.py` | `GET /api/games`: active from registry + finished from PG (D-e). |
| Catch-up snapshot (N9, F5) | `spectate/sse.py` + `game/game.py` | snapshot-as-first-event; `Game.spectator_snapshot()` (D-a/D-b). |
| Live move history (N5) | `game/game.py` + `game/worker.py` | `LiveState.moves` appended each ply (D-c). |
| Replay endpoint (F5) | `spectate/games.py` | `GET /api/games/{id}`: LiveState or PGN → uniform moves[] (D-d). |
| SSE game_over rating (Q6) | `game/worker.py` | publish `rating` on the game_over event (D-f). |
| Ambient house games (ADR-0022 Kind-1) | `game/ambient.py` + `game/house_bots.py` + `app.py` + `alembic 0004` | supervisor maintains N house-vs-house, rated + persisted via the normal launcher (D-g/D-h). |
| Row-locked rating write (D-g2) | `persistence/finalize.py` | `with_for_update()` on bot loads — safe under concurrent ambient finalization. |
| 2nd house identity seed | `alembic/versions/0004_*.py` + `game/house_bots.py` | data-only seed of `house-random-2` (D-h). |
| Dashboard / lobby UI (U1) | `frontend routes/+page.svelte` + `lib/api.ts` | poll + clickable live-game cards (D-j). |
| Watch + replay UI (U2) | `frontend routes/watch/+page.svelte` + `lib/{Board,ReplayControls}.svelte` | catch-up + tail + scrub (D-j). |
| Config knobs | `config.py` | `ER_AMBIENT_*`, `ER_LOBBY_*` (D-g/D-e). |

## Key contracts
```python
# game/game.py
@dataclass
class LiveState:
    ...                                              # existing
    moves: list[dict] = field(default_factory=list)  # [{ply,uci,san,fen}] — replay source (D-c)

class Game:
    def spectator_snapshot(self) -> Optional[dict]:  # None if no live state (D-b)
        # {type:"snapshot", game_id, state, white{name,rating}, black{name,rating},
        #  time_control{base_seconds,increment_seconds}, initial_fen, fen, ply, to_move,
        #  last_move, clocks{white_ms,black_ms}, moves:[{ply,uci,san,fen}]}

# game/registry.py
class GameRegistry:
    def list_active(self) -> list[Game]: ...         # state in {paired, in_progress} (D-e)

# spectate/games.py  (anonymous, read-only, CORS like SSE)
GET  /api/games        -> {"games": [LobbyEntry, ...]}          # active(registry) + finished(PG, LIMIT N)
GET  /api/games/{id}   -> GameView                              # replay/detail (live or PG-PGN)
# LobbyEntry: {game_id, state, white{name,rating}, black{name,rating},
#              time_control{base_seconds,increment_seconds}, ply, to_move, started_at, result?, termination?}
# GameView:   {game_id, state, white{name,rating,bot_id}, black{...}, time_control, initial_fen,
#              moves:[{ply,san,uci,fen}], result, termination, final_fen,
#              rating:{white:{before,after}, black:{before,after}}?}

# game/ambient.py
class AmbientSupervisor:
    def __init__(self, registry, launcher, house_a, house_b, *, n=2, tc, move_delay=1.0): ...
    async def start(self) -> None: ...   # spawn up to n via launcher.launch; re-fill on each finish
    async def stop(self) -> None: ...    # cancel supervision (launcher owns the game tasks)

# persistence/finalize.py (D-g2)
#   white = await session.get(BotRow, id, with_for_update=True)   # row lock; safe under
#   black = await session.get(BotRow, id, with_for_update=True)   # concurrent ambient finalize
```

## Build sub-steps (order within V6) — each ends demoable/testable
1. **Live move history + catch-up snapshot.** `LiveState.moves` (appended in `run_game`);
   `Game.spectator_snapshot()`; SSE emits the snapshot as the first event; document the ply-dedup
   contract. **Checkpoint:** unit — a spectator that connects mid-game receives a `snapshot` first
   (correct fen/ply/clocks/players + full `moves`), then the tail with no gap; a move landing at the
   join boundary is deduped by ply, never lost. (Extend `tests/unit/test_v1_spectate*.py`.)
2. **Lobby + replay REST.** `GameRegistry.list_active()`; `spectate/games.py` — `GET /api/games`
   (active-from-registry + finished-from-PG) and `GET /api/games/{id}` (LiveState- or PGN-projected
   uniform moves[]); mount the router. `ER_LOBBY_*` knobs. **Checkpoint:** unit — `GET /api/games`
   lists a running game with players/ratings/ply/to_move; a bad id 404s. Integration (real DB) — a
   finished game appears in the finished-list and `GET /api/games/{id}` reconstructs its move-list
   from the stored PGN (per-ply fen matches a python-chess walk).
3. **SSE game_over ratings (Q6).** Worker publishes `rating` on the `game_over` event when the
   finalizer returned a result. **Checkpoint:** integration — two bots play to a decisive result; the
   SSE `game_over` event carries `rating.white/black {before,after}` matching the persisted `games`
   row; an ABORTED game's `game_over` omits `rating`.
4. **Ambient house bots (rated + persisted).** Migration `0004` seeds `house-random-2`; second
   `RandomBot` identity in `house_bots.py`; `AmbientSupervisor` (D-g) started/stopped by the lifespan;
   `with_for_update()` row lock in the finalizer (D-g2); `ER_AMBIENT_*` knobs. **Checkpoint:**
   integration — with `ER_AMBIENT_GAMES=2`, `GET /api/games` shows 2 house-vs-house active games
   shortly after startup; when one ends a replacement appears (count returns to 2) and the finished
   game is persisted (a `games` row with both house bots + rating cols) and appears in the finished
   list; with `ER_AMBIENT_GAMES=0` none run (CI/unit default). A concurrent-finalize test asserts two
   games sharing a house bot both apply their rating update (no lost write).
5. **Frontend: lobby + watch + replay + styled board.** Split the route (`/` lobby, `/watch` watch);
   `lib/Board.svelte`, `lib/ReplayControls.svelte`, `lib/api.ts`; catch-up (snapshot→tail) with ply
   dedup; live-follow vs scrub; finished-game replay via `GET /api/games/{id}`; rating change shown at
   game_over. **Checkpoint:** `npm run check` (svelte-check) green; manual `make demo` — open the
   dashboard, see the live lobby (incl. ambient games), click a game, watch from the correct current
   state, scrub back to move 1 and step forward.
6. **Playwright smoke e2e (Q6).** Add Playwright + a `tests/e2e/` smoke that boots the stack (or runs
   against `make dev`/preview), loads the dashboard, waits for an ambient game in the lobby, clicks it,
   asserts the board renders from the catch-up snapshot, and scrubs replay to move 1. Wire a CI job
   (browser install). **Checkpoint:** the smoke test passes locally + in CI (the ADR-0023 end-to-end
   smoke, now meaningful).
7. **Docs + cleanup + demo.** CLAUDE.md V6 → ✅ (+ build-status row); slices.md V6 row + completion
   note; ADR-0015 (catch-up/replay/lobby realized), ADR-0022 (Kind-1 ambient realized + rated in V6),
   DEVELOPER-WORKFLOWS/WORKFLOW-ADOPTION (Playwright/Phase-D adopted), PROTOCOL spectator-note; this
   plan's "deviations as built" + "open items resolved/carried". Full fast gate + integration suite +
   e2e smoke green; PR finalized.

## Tests (at the seams — mirrors V1–V5 layering)
- **Unit (`tests/unit/`, no infra — in-process ASGI / live-uvicorn-no-DB):**
  - Catch-up: connect mid-game → `snapshot` first (fen/ply/clocks/players/moves), then the tail;
    join-boundary move deduped by ply; PAIRED-before-live → no snapshot, `game_start` from the tail.
  - Lobby: `GET /api/games` lists an active game with the right fields; `GET /api/games/{id}` for a
    live game projects `LiveState.moves`; unknown id → 404.
  - `spectator_snapshot()` / `list_active()` shape units.
- **Integration (`tests/integration/`, live uvicorn + testcontainers Postgres):**
  - Finished-game replay: after a real game finalizes, `GET /api/games/{id}` reconstructs the move
    list from the stored PGN (per-ply fen == python-chess walk); it appears in the finished lobby list.
  - SSE `game_over` rating: a decisive game's SSE `game_over` carries `rating` matching the `games`
    row; ABORTED omits it.
  - Ambient (rated + persisted): `ER_AMBIENT_GAMES=2` → 2 house-vs-house active in the lobby; respawn
    on finish; a finished ambient game persists a `games` row + appears in the finished list. Concurrent
    finalize of two games sharing a house bot both apply (no lost rating write, D-g2).
- **Seam reuse:** extend `tests/support/fake_client.py` (a spectator-connect helper if useful) and
  reuse `live_server(...)`, `always_pair`, `matcher_kwargs`, `FakeBotAuthenticator`. Ambient/lobby
  tests set `ER_AMBIENT_GAMES` via `create_app` DI knobs (add an `ambient_kwargs`-style seam, mirroring
  `hb_kwargs`).
- **Frontend:** `npm run check` (svelte-check) + a **Playwright smoke** (Q6) — dashboard → watch →
  replay-to-move-1 — wired into CI (browser install).

## Out of scope (pinned to the slice that proves it)
Packaged SDK / UCI bridge → **V7** · bot-management UI (create-bot / see-key / list-your-bots in the
browser) → later polish (V2 REST already exists) · a dedicated **lobby SSE** stream (poll is the MVP,
ADR-0015 F3) → post-MVP · Redis-backed fan-out / multi-worker → scale-out (ADR-0015 K2) · leaderboards
/ per-time-control ratings / rating history charts → post-MVP · inline SVG piece set / board
animations → polish · a broad Playwright suite (only a single smoke test is in V6, Q6) → later.
**No DDL schema change** — only the `0004` house-bot seed (D-i).

## Open items (to carry)
- **O-1 (Q4):** ambient games are rated + persisted (D-g, owner override) — house ratings drift on the
  infinite ambient stream (accepted per ADR-0022; harmless until a leaderboard exists) and finished
  ambient games enter the `games` table + finished lobby list. Revisit with a leaderboard / house-bot
  ladder, or reconsider unrated if drift becomes noisy.
- **O-2 (Q1):** the finished-lobby list is a simple `LIMIT 20 ORDER BY finished_at DESC` — no
  pagination / filtering. Add if the lobby needs history browsing.
- **O-3 (catch-up dup):** a join-boundary move can be delivered in both the snapshot and the tail; the
  client dedups by ply (D-a). Documented as the contract, not a bug.
- **O-4 (restart & replay):** a live game in flight at a server restart loses its in-memory
  `LiveState` (moves history) — only finished games (Postgres PGN) replay across a restart. Acceptable
  at single-process MVP (a mid-game restart already drops the game, V4/ADR-0020).
- **O-5 (Playwright breadth, Q6):** V6 ships ONE smoke e2e (dashboard→watch→replay); a fuller browser
  suite (owner flows, error paths) is later. The ADR-0023 end-to-end smoke is now realized.
- **O-6 (lobby poll vs SSE):** polling every 3s is fine at MVP traffic; a lobby SSE stream (ADR-0015
  F3) is the scale path.
- **O-7 (D-g2 lock scope):** `with_for_update()` serializes rating writes correctly within Postgres;
  it does not exist on the DB-free house-direct path (no session) — fine, that path doesn't rate.
- **O-8 (ambient shutdown noise):** `AmbientSupervisor.stop()` cancels in-flight `run_game` tasks,
  which logs benign `asyncio` "Task was destroyed but it is pending" warnings (the loop's inner
  `controls.get()`/`request_move` awaits aren't drained on external cancellation). Harmless (only on
  shutdown/teardown, no correctness impact); a tidy fix would give `run_game` a cancellation cleanup
  path. Deferred.
