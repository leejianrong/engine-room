---
shaping: true
---

# V4 Plan — Resilience

**Status: 🔨 IN PROGRESS (2026-07-09).** The owner confirmed the three load-bearing forks on
2026-07-09 — **D-i** (seat owns the inbox), **D-iii** (per-connection ping task, 10s/30s), and
**D-vi** (minimal terminal stash) — after a visualized walkthrough of the options. The lower-fork
decisions (D-ii/D-iv/D-v/D-vii) follow the recommendations below by owner deferral. All D-* are now
pinned; implementation proceeds sub-step by sub-step. Built on `feat/v4-resilience`.

Implementation plan for slice **V4** (from Shape A, part A4). Higher levels:
[slices.md](slices.md) (V4 row), [shaping.md](shaping.md) (R's, Shape A, A4 thickening row).
Mirrors the format of [V3-plan.md](V3-plan.md). Ground truth remains the ADRs +
[PROTOCOL.md](../design/PROTOCOL.md); where this plan and the docs disagree, **the code wins and the
docs get updated** (CLAUDE.md, PROTOCOL, the affected ADRs).

## Goal (definition of done)
A bot **killed mid-game reconnects with the same key and resumes the same seat**, finishing the game
(PROTOCOL §8: `welcome.active_game` populated; a re-sent `your_turn` if it is the bot's turn). The
**clock keeps running while it is away** (ADR-0025 #3 — the bot ate its own time; there is **no**
separate reconnect window). A **blind move-resend after a blip is safe** — a duplicate `move` at an
already-applied ply is **re-acked, never re-applied** (PROTOCOL §9). An **illegal or unparseable move
on your turn is an instant forfeit** (`game_over`, termination `illegal_move`, ADR-0016 B7) — flipping
V1's report-and-ignore. A **heartbeat** (ping/pong, §10) detects a half-dead socket, and **mutual
abandonment** (both seats gone) **aborts** the game (`ABORTED`, no result, no rating — ADR-0010 /
ADR-0016 I7). A single disconnected bot is **never** forfeited by heartbeat — only by its own clock.
All of this stays single-process / in-memory (R5); **no schema change** (resilience is live-state).

## What thickens (A4 → V4)
Per [shaping.md A2–A7 table](shaping.md#a2a7--thickening-breadboarded-per-slice-in-the-slices-doc):
> N1/N5 resilience — reconnect-resume the same seat, `ply`-idempotency, illegal-move forfeit,
> heartbeat/liveness → mutual-abandonment ABORT.

No new *subsystems*. V4 thickens:
- **N1 (session/handshake):** `welcome.active_game` becomes real; the handshake rebinds a live game
  seat to the new session; a per-connection heartbeat task is added.
- **N5 (game loop / seat):** the seat's inbound becomes durable across session swaps; `ply`
  idempotency (§9) and illegal-move forfeit (B7) land in the seat; `run_game` gains an ABORTED exit
  and a live-state snapshot the reconnect payload reads.
- **N8 (finalize):** an `ABORTED` game writes a `games` row with no rating.

N2–N4 (seek/matcher/house), N6 (clock), N7/N9 (pubsub/SSE), N10 (persistence infra) are untouched
except that seat/live-state creation moves from `run_game` into the launcher so a reconnect that
races the first move still finds a bound seat (see D-i).

## The core problem (why this slice is real work)
Today a `WsSeat` holds a `Session` ref and reads that session's `inbound` queue; the endpoint routes
`move` frames to `session.inbound`. On reconnect, **newest-wins** (ADR-0016 A6) makes a **new
`Session` with a new `inbound` queue** and closes the old socket. The running game loop is blocked on
`await old_session.inbound.get()` — a queue that will **never** receive the reconnected bot's moves.
So the bot silently flags. V4 must let the **live game follow a session swap** and expose enough live
state to answer `welcome.active_game`.

## Build-time decisions

### Pinned (low-fork; rationale below)
| # | Decision | Rationale |
|---|----------|-----------|
| D-a | **No schema change / no Alembic migration.** All resilience state (live board/clock/ply, applied-move history, active-game index, last-pong, abort signal) is **in-memory, single-process** (R5, ADR-0020/0025 #2). The only DB write is an `ABORTED` `games` row, and `result String(16)` / `termination String(32)` already accept `"aborted"` (ADR-0008 vocab). | Resilience is live-state; nothing durable is added. Keeps the slice thin and reversible. |
| D-b | **Best-effort outbound sends during a game.** `Session.send` already suppresses on `terminate`; V4 makes the seat's in-game sends (`your_turn`/`move_ack`/`game_over`/`ping`) **swallow send failures** so a dead/half-dead socket never crashes `run_game`. The **clock governs** (ADR-0025 #3): a bot whose `your_turn` couldn't be delivered still has its clock running and either reconnects or flags. | Without this, the first send to a dropped socket kills the game task. Reconnect + clock-as-arbiter only work if the loop survives a dead peer. |
| D-c | **`start_grace_ms` stays advertised (10000) but is not a separate enforced timer.** PAIRED→IN_PROGRESS is immediate; there is **no** reconnect/readiness window (ADR-0025 #3 supersedes ADR-0004). The only PAIRED/early ABORT is the *mutual-abandonment* path (both gone), which the same liveness check covers from `in_progress` onward. | Do not reintroduce ADR-0004's window. One governor (the clock) + one abort trigger (both gone). |
| D-d | **Tunable heartbeat numbers live in `config.py`** (`ER_HB_*`), injected via `create_app`/`app.state` (mirrors `ER_MM_*`). Tests pass tiny values. | Same DI pattern V3 used; deterministic liveness tests without real 30s waits. |
| D-e | **MVP scope held:** single process, no Redis; Blitz only (3+0/5+0); ports :8001/:5174/:5433; frontend↔backend CORS. Resign/draw/auto-draw and **real Elo rating updates stay V5**; rate limits / griefing cooldowns stay V-later. | R5; unchanged from V1–V3. |

### Confirmed 2026-07-09 (the three load-bearing forks) + deferred (lower-fork)
The owner confirmed **D-i / D-iii / D-vi** directly (after the visualized options walkthrough); the
remaining D-* were deferred to the recommendation below.
| # | Decision | Pinned choice |
|---|----------|---------------|
| **D-i** ✅ | **Seat ↔ session rebinding: how does the live loop follow a newest-wins swap?** | **Confirmed — Seat owns a durable inbox + a swappable `session`, reached via a `bot_id→(game, seat)` index; live state lives on the `Game`.** The only design where a session swap can't lose an in-flight move. See [Seat rebinding](#seat-rebinding-d-i). |
| **D-ii** | **`active-game` lookup + resume payload shape.** | **Add `bot_id→Game` (+ recent-terminal) index to `GameRegistry`, set at launch, cleared at terminal; `Game.resume_payload(bot_id)` emits the §8 fields.** See [Active-game lookup](#active-game-lookup-d-ii). |
| **D-iii** ✅ | **Heartbeat architecture + which numbers to pin.** | **Confirmed — Per-connection ping task in the endpoint (no central sweeper); `pong` handled in the single receive loop; liveness timeout closes the socket → the disconnect path checks both-gone → ABORT.** Pin ping **10s**, liveness **30s** (~3 missed), `ER_HB_*`-tunable. See [Heartbeat](#heartbeat-d-iii). |
| **D-iv** | **ABORTED finalization mechanics.** | **A per-game `abort` event; `run_game` awaits move-or-abort each turn; on abort → `state="aborted"`, `result="aborted"`, `termination="aborted"`, finalize a `games` row with `rating=None`.** See [ABORTED](#aborted-finalization-d-iv). |
| **D-v** | **`ply`-idempotency state + location (seat vs worker).** | **Worker owns `expected_ply` (its loop `ply`) + an `applied: dict[ply, uci]` history; the seat's read loop does the §9 classification + re-ack.** See [Idempotency](#ply-idempotency-d-v). |
| **D-vi** ✅ | **"Flagged/finished while away" → deliver `game_over` on reconnect?** | **Confirmed — Yes, minimal:** stash the terminal `game_over` per bot at finalize; if reconnect finds no active game but a recent terminal, send it once. See [Terminal-on-reconnect](#terminal-on-reconnect-d-vi). |
| **D-vii** | **How reconnect/idempotency/heartbeat are exercised at the WS seam.** | **Live-uvicorn harness (kill a socket mid-game, reconnect same key, assert resume) + unit tests on seat/worker with a fake session and injectable clock** (mirrors V3's `test_v3_matchmaking_live.py` + fake-clock unit tests). See [Tests](#tests-at-the-seams). |

---

### Seat rebinding (D-i)
Three options were weighed (per the kickoff):

1. **Per-bot durable "mailbox" decoupled from `Session`.** Moves route to a bot-keyed mailbox that
   outlives any session; the loop reads the mailbox, the session is only a transport.
2. **`bot_id→(game, seat)` registry index; reconnect rebinds the seat's session/inbound.**
3. **The loop awaits an explicit rebind signal** and re-reads from the new session's queue.

**Recommendation — a hybrid of (1) + (2):**
- **The inbox moves onto the `WsSeat`** (`seat.inbound: asyncio.Queue`), off `Session`. The seat is
  the bot's durable game-side identity (ADR-0009: seat bound to bot, not session), so a blocked
  `await seat.inbound.get()` **survives a session swap** — the reconnected endpoint puts the move into
  the *same* seat inbox. No "wake the loop" dance, no lost move.
- **`seat.session` stays mutable** (`seat.rebind(new_session)`); it is only the *outbound* transport
  (`your_turn`/`move_ack`/`game_over`/`ping`). Rebinding is a plain attribute swap — the in-flight
  `get()` doesn't care.
- **A `bot_id→(game, seat)` index** (on `GameRegistry`, D-ii) lets the endpoint (a) route an inbound
  `move` to the right seat inbox and (b) find the seat to rebind on reconnect.
- **Live state lives on the `Game`** (`game.live`, D-ii) so `welcome.active_game` reads a consistent
  snapshot regardless of which session is current.

Why not (3): the loop-awaits-a-signal design needs the loop to abandon its current `get()` and
re-await, which reintroduces exactly the lost-move race D-i exists to kill. Seat-owned inbox makes the
swap invisible to the loop.

**Consequence:** seat + live-state creation moves out of `run_game` into the **launcher** (before
`game_start` is sent and `run_game` is spawned) so a reconnect that races the first move always finds
a bound seat. `run_game` then *operates on* `game.live` and `game.seats` instead of building locals.

### Active-game lookup (D-ii)
`GameRegistry` gains (all in-memory, single-process):
- `_active_by_bot: dict[str, Game]` — set for each **real** (session-backed) seat at `bind_active(game)`
  (called by the launcher); cleared at `unbind_active(game)` (called by `run_game` on any terminal).
- `active_game_for(bot_id) -> Game | None`.
- `_recent_terminal_by_bot: dict[str, Game]` — set at terminal (D-vi).

`Game` gains: `seats: dict[str, Seat]` (by color), `live: LiveState | None`, `seat_for(bot_id)`, and
`resume_payload(bot_id) -> dict` returning the PROTOCOL §8 shape:
```json
{ "game_id","your_color","fen","ply","last_move","clocks":{"white_ms","black_ms"},
  "opponent_draw_offer": false, "to_move" }
```
`LiveState` (updated by `run_game` each half-move): `board: chess.Board`, `clock: Clock`, `ply: int`,
`last_move: dict|None`, `applied: dict[int,str]`. `to_move`/`fen` derive from `board`; `clocks` from
`clock.remaining_ms(...)`. **MVP caveat (open item):** the mover's `remaining_ms` is the value at the
*last charge*, so a resume during a long think slightly over-reports the running clock (the deduction
lands at `charge`). Acceptable at MVP; noted.

### Heartbeat (D-iii)
- **Sender:** a **per-connection ping task** started after the handshake (not a central sweeper — the
  per-connection structure already exists; the endpoint is the natural owner). Every `ping_interval`
  it sends `{"type":"ping","t":<ms>}` and checks liveness.
- **Pong routing:** the endpoint is the **single socket reader**, so `pong` is handled in the receive
  loop exactly like `move` — it records `session.last_pong = now()`. (Ignore `t`-matching for MVP;
  presence of a pong is the signal.)
- **Liveness:** if `now() - last_pong > liveness_timeout`, the ping task **closes the socket** →
  the receive loop raises `WebSocketDisconnect` → the normal disconnect path runs. This is how a
  *half-dead* socket (no TCP FIN) is turned into a real disconnect.
- **Mutual abandonment → ABORT:** in the endpoint's disconnect cleanup, after `remove_if_current`,
  if `session_registry.current(bot_id) is None` (truly gone, not replaced by newest-wins) **and** the
  bot has an active `in_progress` game **and** the opponent seat is a **real** bot with **no** live
  session → fire the game's abort event (D-iv). A **house** opponent is never "gone", so a house game
  never mutually-aborts — the lone bot simply flags on its clock.
- **Numbers to pin now:** `ER_HB_PING_INTERVAL_SECONDS = 10`, `ER_HB_LIVENESS_TIMEOUT_SECONDS = 30`
  (~3 missed pings). `ER_HB_*`-tunable (D-d); tests use tiny values (e.g. 0.05 / 0.15).
- A single disconnected bot is **not** forfeited by heartbeat — heartbeat only closes *its own*
  socket; whether it loses is decided by *its clock* (ADR-0025 #3).

### ABORTED finalization (D-iv)
- Each `Game` gets an `abort: asyncio.Event` (or a flag + the seat inbox). `run_game`'s per-turn wait
  becomes "**move OR abort, under the clock deadline**" (`asyncio.wait([...], FIRST_COMPLETED,
  timeout=deadline)`); if the abort wins → break out of the loop with `result="aborted"`,
  `termination="aborted"`.
- On the ABORTED exit: `game.state="aborted"`, `final_fen = board.fen()`, `pgn = render(board)`;
  if a `finalizer` is set, write the `games` row (`result="aborted"`, `termination="aborted"`,
  **no rating**); `game_over` is sent best-effort to any still-live seat (in true mutual abandonment
  there are none — the sends no-op). Then `unbind_active(game)`.
- **Reconciling with V3's reap-before-pair:** V3's ABORT-equivalent is *ticket-level* — a ticket whose
  session vanished **before** a game exists is silently dropped (no `games` row). V4's ABORT is
  *game-level* — both seats drop **after** the game is live, so a terminal `games` row (`aborted`) is
  written. They are different lifecycle points (QUEUED vs IN_PROGRESS) and do not overlap.

### `ply`-idempotency (D-v)
Per PROTOCOL §9, handled in the **seat read loop** (`WsSeat.request_move`) using history the **worker**
owns:
- **Worker** tracks `expected_ply` (its loop `ply`) and, after each `board.push`, records
  `applied[ply] = uci` (in `game.live.applied`) before incrementing.
- **Seat**, per inbound `move` while awaiting the current `ply`:
  - `msg.ply == ply` → parse. **Unparseable or illegal → forfeit** (raise `IllegalMoveForfeit`;
    the worker turns it into `game_over` `illegal_move`, opponent wins — ADR-0016 B7). Legal → return
    the uci (loop applies + `move_ack`).
  - `msg.ply < ply` and `applied[msg.ply] == msg.uci` → **duplicate**: re-send `move_ack` for that
    ply, **do not re-apply**; keep waiting.
  - `msg.ply < ply` and `applied[msg.ply] != msg.uci` → **stale/conflicting**: ignore, **not**
    penalized; keep waiting.
  - `msg.ply > ply` → `error {INVALID_PLY}`; keep waiting.

This flips V1's "illegal move reported-and-ignored" to **forfeit**, and adds the dup/stale/future
handling V1 lacked. `HouseSeat` is unaffected (it never resends; it takes the same signature and
ignores `applied`).

### Terminal-on-reconnect (D-vi)
PROTOCOL §8 says a bot that flagged while away "instead receives `game_over`". After `unbind_active`,
`active_game_for` returns `None`, so a plain reconnect would see `active_game:null` and be left to
infer the loss. **Recommended minimal fix:** at finalize, stash the seat's `game_over` payload in
`_recent_terminal_by_bot[bot_id]`; on reconnect, if there is no active game but a recent terminal
exists, send that `game_over` once (and drop it). Bounded by bot count (single-process); eviction
policy is an open item. **Alternative:** defer entirely to V6 (dashboard/replay lets a human see the
result) and ship V4 with `active_game:null` only. Recommendation: include the minimal stash so the
reconnect story is complete for a headless bot.

## Project layout (changes this slice)
```
server/engine_room/
  ws/
    session.py          # inbound queue REMOVED (moves to seat); + last_pong field/helpers
    bot_endpoint.py     # reconnect-resume (welcome.active_game + rebind); move→seat routing;
                        #   ping task + pong handling; disconnect → mutual-abandonment check
    session_registry.py # unchanged (newest-wins already correct)
  game/
    seat.py             # WsSeat owns inbound; §9 idempotency + illegal-move forfeit; best-effort sends
    worker.py           # operates on game.live; applied history; move-or-abort wait; ABORTED exit
    game.py             # + LiveState, Game.seats/live/abort, seat_for(), resume_payload()
    registry.py         # + _active_by_bot / _recent_terminal_by_bot, bind/unbind/active_game_for
    house_bots.py       # unchanged
  matchmaking/launcher.py # create seats + live state + bind_active BEFORE game_start + spawn
  protocol/messages.py    # + Ping (outbound), Pong (inbound); NO_ACTIVE_GAME usage; parse-map
  config.py               # + ER_HB_* knobs (D-d)
# no Alembic migration (D-a); no frontend change (resilience is bot-facing)
```

## Affordance → module map
| Affordance | Module | Notes |
|-----------|--------|-------|
| Reconnect-resume (N1) | `ws/bot_endpoint.py` + `game/registry.py` + `game/game.py` | `welcome.active_game`; rebind seat.session; resend `your_turn`. |
| Durable seat inbox (N5) | `game/seat.py` + `ws/session.py` | inbox moves to the seat; survives session swap (D-i). |
| `ply`-idempotency (N5, §9) | `game/seat.py` (+ `game/worker.py` history) | dup re-ack / stale ignore / future INVALID_PLY (D-v). |
| Illegal-move forfeit (B7) | `game/seat.py` + `game/worker.py` | flip ignore→forfeit; `game_over` `illegal_move`. |
| Heartbeat / liveness (§10) | `ws/bot_endpoint.py` + `ws/session.py` + `config.py` | per-conn ping task; pong in receive loop (D-iii). |
| Mutual-abandonment ABORT (I7) | `ws/bot_endpoint.py` + `game/worker.py` + `game/game.py` | both-gone → abort event → ABORTED (D-iv). |
| ABORTED finalize (N8) | `game/worker.py` + `persistence/finalize.py` (reused) | `games` row, no rating. |
| Active-game index | `game/registry.py` | `bot_id→Game` set at launch / cleared at terminal (D-ii). |
| Live-state snapshot | `game/game.py` + `game/worker.py` | `LiveState` feeds `resume_payload` (D-ii). |
| HB config knobs | `config.py` | `ER_HB_*` (D-d). |

## Key contracts
```python
# game/game.py
@dataclass
class LiveState:
    board: "chess.Board"
    clock: "Clock"
    ply: int = 0
    last_move: dict | None = None
    applied: dict[int, str] = field(default_factory=dict)   # ply -> uci (idempotency, §9)

@dataclass
class Game:
    ...                          # existing fields
    seats: dict[str, "Seat"] = field(default_factory=dict)  # "white"/"black" → seat
    live: LiveState | None = None
    abort: asyncio.Event = field(default_factory=asyncio.Event)
    def seat_for(self, bot_id: str) -> "Seat | None": ...
    def resume_payload(self, bot_id: str) -> dict: ...       # PROTOCOL §8 shape

# game/seat.py
class IllegalMoveForfeit(Exception):
    """Raised by a WsSeat when the move AT the current ply is illegal/unparseable
    (ADR-0016 B7). run_game turns it into game_over{termination:'illegal_move'}."""
    def __init__(self, color: str): self.color = color

class WsSeat:
    inbound: asyncio.Queue           # durable; survives session swaps (D-i)
    def rebind(self, session: "Session") -> None: ...
    async def resend_your_turn(self, live: LiveState) -> None: ...   # on reconnect if to_move==self

# game/registry.py (additions)
def bind_active(self, game: Game) -> None: ...        # index real seats' bots → game
def unbind_active(self, game: Game) -> None: ...      # clear + record recent terminal (D-vi)
def active_game_for(self, bot_id: str) -> Game | None: ...
def recent_terminal_for(self, bot_id: str) -> Game | None: ...

# protocol/messages.py
class Ping(BaseModel):  type: Literal["ping"] = "ping"; t: int      # outbound
class Pong(BaseModel):  type: Literal["pong"]; t: int               # inbound; add to _CLIENT_MODELS
```

## Build sub-steps (order within V4) — each ends demoable/testable
1. **Protocol + config.** `Ping`/`Pong` models + parse-map; `ER_HB_*` settings; wire `NO_ACTIVE_GAME`
   usage. **Checkpoint:** unit — parse `pong`; `ping` serializes; HB settings default/override.
2. **Seat idempotency + illegal-move forfeit (seat-owned inbox).** Move `inbound` onto `WsSeat`;
   implement §9 classification + re-ack + `IllegalMoveForfeit`; worker maintains `applied` and catches
   the forfeit → `game_over` `illegal_move`; best-effort sends (D-b). **Checkpoint:** unit — drive a
   seat/worker with a scripted inbox: dup→re-ack (single apply), stale→ignore, future→INVALID_PLY,
   illegal/unparseable→forfeit. Existing V1 game-loop tests still green.
3. **Live state + active-game index + launcher refactor.** `LiveState`/`Game.seats/live/abort/
   seat_for/resume_payload`; `GameRegistry` bind/unbind/active_game_for; launcher creates seats +
   live + `bind_active` before `game_start`/spawn; `run_game` operates on `game.live` and unbinds at
   terminal; endpoint routes `move`→seat via the index (`NO_ACTIVE_GAME` otherwise). **Checkpoint:**
   unit — `resume_payload` shape from a mid-game `LiveState`; `move` routes to the seat; all prior
   tests green.
4. **Reconnect-resume in the endpoint.** Populate `welcome.active_game`; `seat.rebind(session)`;
   resend `your_turn` if it's the bot's turn; deliver a recent-terminal `game_over` (D-vi).
   **Checkpoint:** integration (live uvicorn) — kill a mid-game socket, reconnect same key, assert
   `welcome.active_game` + resume + play to a natural terminal; a **blind move-resend** after the blip
   is re-acked (not double-applied).
5. **Heartbeat + mutual-abandonment ABORT.** Per-connection ping task; `pong` in the receive loop;
   liveness-timeout close; disconnect cleanup → both-gone → abort event → `run_game` ABORTED exit →
   `games` row (no rating). **Checkpoint:** integration — both bots disconnect → game ABORTS (row
   `result="aborted"`, no rating); a bot that stops ponging is closed after a tiny liveness timeout;
   a **single** disconnect does **not** abort (the loop keeps running; clock governs).
6. **Docs + cleanup + demo.** Update CLAUDE.md build-status (V4 ✅), slices.md V4 row + completion
   note, this plan's status → done; reconcile PROTOCOL §8/§9/§10 with the code; add an ADR-0004
   "superseded by ADR-0025 #3, realized in V4" pointer. ruff clean; full gate green; verify
   `make demo` (kill the demo bot mid-game, watch it reconnect and finish). Finalize the PR.

## Tests (at the seams — mirrors V1/V2/V3 layering)
- **Unit (`tests/unit/`, no infra):**
  - Seat/worker idempotency (sub-step 2): scripted inbox → dup re-ack (asserts single `board.push`),
    stale ignore, future `INVALID_PLY`, illegal/unparseable → forfeit `game_over`.
  - `resume_payload` shape + `GameRegistry` bind/unbind/active_game_for (sub-step 3).
  - Liveness "is-stale" math with an **injectable clock** (D-d) — deterministic without real waits.
- **Integration (`tests/integration/`, live uvicorn like `test_v3_matchmaking_live.py`):**
  - **Reconnect-resume** (sub-step 4): two bots (or bot-vs-greeter) mid-game; drop one socket;
    reconnect with the same key; assert `welcome.active_game`, a re-sent `your_turn`, and play-out.
  - **Blind resend** (sub-step 4): resend the last `move` after reconnect → re-acked, board unchanged.
  - **Mutual abandonment** (sub-step 5): both sockets close mid-game → game ABORTS (assert an
    `aborted` `games` row via a real-DB variant, or the in-memory `Game.state`).
  - **Heartbeat close** (sub-step 5): a bot that never sends `pong` is disconnected after a tiny
    `ER_HB_LIVENESS_TIMEOUT_SECONDS`.
- **Seam reuse:** extend `tests/support/fake_client.py` — a `reconnect(...)` helper, `pong()`, and a
  "resume then finish" flow; reuse the `live_server(...)` harness + `matcher_kwargs`/`hb_kwargs`.

## Out of scope (pinned to the slice that proves it)
Resign / draw / auto-draw / **real Elo rating updates + K-factor** → V5 (ADR-0011/A5) · dashboard /
lobby / catch-up / replay / bot-management UI → V6 · packaged SDK / UCI → V7 · rate limits & griefing
cooldowns (ADR-0019 H2/H3) → V-later · ambient pool-resident house bots / 2nd house identity → V6 ·
Redis-backed live-state / cross-worker reconnect → post-MVP scale-out. **Reconnect is governed by the
clock, not a window** — ADR-0004's reconnect window is **not** reintroduced (ADR-0025 #3).

## Open items (to resolve during the slice)
- **O-1 (D-vi):** include the minimal recent-terminal `game_over`-on-reconnect stash, or defer? (Affects
  whether a bot that flags while away learns its result before V6.) — **awaiting confirmation.**
- **O-2 (D-ii caveat):** resume-payload clocks show the last-charged `remaining_ms` (a small
  over-report for the mover mid-think). Acceptable at MVP; revisit if a bot's resume logic needs the
  running value.
- **O-3 (D-iii):** liveness tie-in assumes at most one active game per bot (the index is `bot_id→Game`).
  True at MVP (a bot seeks → plays → then seeks again); revisit if concurrent games per bot ever land.
- **O-4:** `_recent_terminal_by_bot` / `_active_by_bot` eviction — unbounded in principle
  (single-process, bot-count-bounded in practice). Fine for MVP; a TTL/size cap is a V-later cleanup.
- **O-5 (docs):** on completion, reconcile PROTOCOL §8/§9/§10 with the built behavior and add the
  ADR-0004→ADR-0025 "realized in V4" pointer (sub-step 6).
