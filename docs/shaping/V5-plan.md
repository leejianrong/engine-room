---
shaping: true
---

# V5 Plan — Outcomes & real ratings

**Status: 🚧 DRAFT (2026-07-09).** On `feat/v5-outcomes` off merged V4 (`d472d14`, PR #11). This
plan is written first (mirroring [V4-plan.md](V4-plan.md)); the **open decisions** in
[§ Decisions to confirm](#decisions-to-confirm-before-implementing) are put to the owner **before**
any code lands. Ground truth is the ADRs + [PROTOCOL.md](../design/PROTOCOL.md); where this plan and
the docs disagree, **the code wins and the docs get updated** (CLAUDE.md, PROTOCOL, the affected
ADRs).

Implementation plan for slice **V5** (Shape A, part A5). Higher levels: [slices.md](slices.md) (V5
row), [shaping.md](shaping.md) (R's, Shape A, A2–A7 thickening row).

## Goal (definition of done)
Bots **resign** and **agree draws**; the server **auto-draws** every standard drawing condition; and
**ratings move on FINISHED** with a real Elo update written atomically with the game record.
Concretely:
- **Resign** → immediate `game_over`, `termination "resignation"`, the opponent wins (ADR-0008).
- **Draw offer/accept** → `game_over`, `result "draw"`, `termination "agreement"` (ADR-0008 / 0016
  D6). A standing offer is surfaced to the opponent via `your_turn.opponent_draw_offer`; the
  opponent's move **implicitly declines** it (D6).
- **Auto-draws (no claim, D8)** → the server ends stalemate / insufficient-material / threefold /
  fifty-move / fivefold / seventy-five-move automatically. **Timeout vs insufficient material** →
  `DRAW / insufficient_material`, not a win (D7).
- **Real Elo** → compute `{before, after}` per bot with a K-factor (ADR-0011), write per-color rating
  columns **and** update `bots.rating` (+ a rated-games counter) in the **one** finalize transaction
  (ADR-0025 #5); `game_over.rating` carries the real numbers. **ABORTED games still write no rating.**

Stays single-process / in-memory for live state (R5); the **only** new durable state is rating
columns + a rated-games counter (Alembic **0003** — the first schema change since V2's 0002).

## What thickens (A5 → V5)
Per [shaping.md A2–A7 table](shaping.md#a2a7--thickening-breadboarded-per-slice-in-the-slices-doc):
> N5/N8 outcomes — resign/draw control messages, server auto-draws, real Elo on FINISHED.

No new *subsystems*. V5 thickens:
- **N5 (game loop / seat):** the loop learns non-move terminals (resign, draw-agreement) and a
  draw-offer lifecycle; `board.outcome(claim_draw=True)` + the D7 timeout rule replace the
  automatic-only terminal check.
- **N8 (finalize):** the finalizer computes the Elo delta and updates `bots.rating` in the same txn
  as the `games` row (ADR-0025 #5).
- **Protocol:** three new inbound control messages (`resign`/`draw_offer`/`draw_accept`); the
  already-defined-but-no-op `Move.offer_draw` and `YourTurn.opponent_draw_offer` become real;
  `GameOver.rating` carries real values.
- **A new pure module** `game/ratings.py` (Elo math) — distinct from `matchmaking/elo.py`, which is
  the *pairing window* (a different concern; not touched except optionally O-3).

N1–N4 (handshake/seek/matcher/house), N6 (clock), N7/N9 (pubsub/SSE), N10 (persistence infra) are
untouched except the matcher's optional anti-rematch refinement (O-3, deferred by default).

## The core problem (why this slice is real work)
Two hard points:

1. **Control-message interleaving.** Today the seat-to-move's `WsSeat.request_move` is the *only*
   inbox reader, and it expects a `Move` at the current `ply` (V4 D-i). A `resign` or `draw_accept`
   can arrive **when it is NOT the sender's turn** — from the seat whose inbox nobody is draining. So
   there must be a game-level path that reaches the loop regardless of whose turn it is, without
   disturbing the in-flight `request_move` (re-sending `your_turn` mid-think would be wrong).

2. **Atomic rating vs the game_over payload.** ADR-0025 #5 requires result + Elo + PGN in **one**
   Postgres transaction, but the per-bot `game_over.rating {before, after}` must reflect the *same*
   numbers that were persisted. The finalizer (the only component with DB access to the rated-games
   counter) must both persist and hand the computed ratings back to the loop so `game_over` is
   consistent with the durable record — and still degrade to a stub when no finalizer is injected
   (the DB-free test/house path).

## Build-time decisions

### Pinned (low-fork; rationale below)
| # | Decision | Rationale |
|---|----------|-----------|
| D-a | **Control messages reach the loop via a per-`Game` control channel, not the seat inbox.** The endpoint routes `resign`/`draw_offer`/`draw_accept` to `game.controls: asyncio.Queue[(color, msg)]` (via the active-game index, exactly like it routes `move` to the seat inbox). `run_game` watches `{move_task, abort_wait, controls}` each turn (extending V4's move-or-abort wait). The seat inbox stays **move-only**. | Solves core-problem #1 cleanly: a control from the non-moving side reaches the loop without anyone draining that seat's move inbox, and without cancelling/re-issuing the mover's `request_move`. Mirrors the existing `abort` event pattern. |
| D-b | **Piggybacked draw offer rides on `Move.offer_draw`; the seat stashes it for the worker.** `WsSeat.request_move` records `self._offer_draw = msg.offer_draw` alongside `_pending_id` when it returns the move; the worker reads it after applying. No new return type. | `Move.offer_draw` already exists on the wire (§6); this makes it real with the smallest change and keeps `request_move`'s `-> str` signature. |
| D-c | **Draw-offer lifecycle lives on `LiveState` (`pending_draw_offer: Optional[color]`).** Set when a side offers (via `offer_draw` or a `draw_offer` control); surfaced as `your_turn.opponent_draw_offer` / `resume_payload.opponent_draw_offer` to the *other* side; **cleared when the opponent-of-the-offerer makes a move** (implicit decline, D6). A `draw_accept` is valid only against a standing offer from the *other* color. | Single source of truth, already the home of live board/clock/ply; survives reconnect (resume_payload reads it). Matches D6 exactly. |
| D-d | **Auto-draws via `board.outcome(claim_draw=True)`; no claim protocol (D8).** The existing `_TERMINATION` map already covers threefold/fifty/fivefold/75-move; flipping `claim_draw=True` makes the server auto-claim threefold + fifty-move. | D8 says the server auto-draws every standard drawing condition and bots never claim. `claim_draw=True` is exactly that; the map needs no new keys. |
| D-e | **Timeout vs insufficient material → DRAW (D7).** On a clock flag, if `board.has_insufficient_material(winner_color)` the result is `draw / insufficient_material`, else the flagging side loses (`timeout`). | D7 verbatim; `python-chess` determines it. |
| D-f | **Rating math is a pure module `game/ratings.py`.** `expected_score(a, b)`, `updated(rating, score, k)`, and `k_factor(games_played)`; no I/O, unit-tested against a table. The finalizer calls it; the worker never computes Elo. | Pure functions are trivially testable and keep Elo out of the loop/DB glue. Distinct from `matchmaking/elo.py` (pairing window). |
| D-g | **The finalizer computes + persists ratings atomically and returns them; the loop sends what was persisted.** `Finalizer.__call__` returns `Optional[FinalizeResult]` carrying per-color `(before, after)`. On FINISHED (not aborted) it reads each bot's current `rating`/`games_played` **inside the txn**, computes new values, writes the four `games` rating columns, and `UPDATE`s both `bots` rows — all in one `session.begin()`. `run_game` passes the returned `(before, after)` into each `seat.game_over`. **Finalizer `None` (DB-free/house-direct tests) → stub `before == after == seat.rating`** (today's behavior). | Satisfies ADR-0025 #5 (one txn) *and* keeps `game_over.rating` consistent with the durable record. DB is the source of truth for the rated-games counter (correct under the single-process MVP; still correct if concurrency ever lands). |
| D-h | **ABORTED writes no rating (unchanged).** The finalizer returns `None` for an aborted game; `game_over.rating` is omitted (already true in `_terminal_game_over`, and `run_game`'s aborted path sends no per-seat rating). | ADR-0010/0011/0016: an aborted game has no fair result. Keep it. |
| D-i | **MVP scope held:** single process, no Redis; Blitz only (3+0/5+0); ports :8001/:5174/:5433; frontend↔backend CORS. **Single global rating per bot** (per-time-control deferred, E8). No rate limits / griefing cooldowns (V-later). Dashboard/lobby/catch-up/replay/ambient house bots stay **V6**; SDK/UCI stay **V7**. | R5 / E8; unchanged from V1–V4. |

### Decisions to confirm (before implementing)
These are put to the owner up front; recommendations are marked ★.

| # | Question | Options / recommendation |
|---|----------|--------------------------|
| **Q1 K-factor** | Pin the Elo K-factor + provisional rule. | ★ **K=32 while provisional (< 30 rated games), K=16 after** (ADR-0011 / 0016 E8 verbatim). Config: `ER_ELO_K_PROVISIONAL=32`, `ER_ELO_K_DEFAULT=16`, `ER_ELO_PROVISIONAL_GAMES=30`, initial 1200 (already the `bots.rating` default). Confirm single global rating (not per-TC). |
| **Q2 Rating columns** | What does 0003 add to `games`, and how do we count provisional games? | ★ Add **four nullable ints** to `games`: `white_rating_before/after`, `black_rating_before/after` (null ⇒ aborted). Add `bots.games_played INTEGER NOT NULL DEFAULT 0`, incremented for each rated bot at finalize (the provisional counter). Deltas are derivable; storing before/after matches the `game_over.rating` shape directly. |
| **Q3 Do house games rate?** | A greeter/house-vs-human game is FINISHED — does it update `bots.rating` for the human bot? For the house bot? | ★ **Rate both bots uniformly** (the house is just another `Bot` row with a rating; keeps finalize uniform and the demo shows movement immediately). Alternative: rate the human only / neither (house is a sparring partner). Same-owner exclusion + house-exempt pairing already limit farm-ability; no rate cooldown at MVP. **Owner call — this affects the finalizer's per-seat loop.** |
| **Q4 Offer timing** | May a bot offer a draw only on its own turn, or any time? Does a standalone `draw_offer` while the opponent is already on move surface this turn or next? | ★ **Accept an offer at any time; surface it on the recipient's *next* `your_turn`** (D6 "surfaced in the opponent's next your_turn"). If the recipient is already mid-think, they see it on the following turn — acceptable at MVP (noted as O-1). Simplest, matches D6 wording. |
| **Q5 Anti-rematch refine (O-3)** | Record last-opponent at **FINISHED** now that finalize state is shared, instead of at pairing? | ★ **Defer** — keep recording at pairing (V3 behavior). It works and is decoupled; wiring finalize→matcher adds a dependency for marginal benefit. Revisit if rematch-churn is observed. (Flip if owner wants it now.) |
| **Q6 SSE game_over ratings** | Should the spectator `game_over` event carry the rating change (for the V6 lobby)? | ★ **Out of scope** — keep the SSE `game_over` payload unchanged; ratings are bot-facing in V5. V6 (dashboard) adds them when it needs them. |

---

### Control interleaving (D-a / D-b / D-c) — the design
Per turn, `run_game` already awaits `{move_task, abort_wait}` under the clock deadline (V4). V5 adds a
**control drain** to the same wait:

```
# per ply (color to move):
move_task  = ensure_future(seat.request_move(...))   # move-only inbox, opponent_draw_offer set from live
t0, deadline = loop.time(), clock.deadline_s(color)
while True:                                           # inner: resolve THIS turn
    ctrl_task = ensure_future(game.controls.get())
    done, _ = await asyncio.wait({move_task, abort_wait, ctrl_task},
                                 timeout=max(0, deadline - (loop.time()-t0)),
                                 return_when=FIRST_COMPLETED)
    if ctrl_task not in done: ctrl_task.cancel()
    if abort_wait in done:       -> ABORTED (V4), cancel move_task, break outer
    if ctrl_task in done:
        color_c, msg = ctrl_task.result()
        - resign(color_c):        opponent(color_c) wins, "resignation" -> break outer
        - draw_accept(color_c):   valid iff live.pending_draw_offer == opponent(color_c)
                                     -> "draw"/"agreement" -> break outer;  else ignore, continue inner
        - draw_offer(color_c):    live.pending_draw_offer = color_c; continue inner (no your_turn re-send)
        (continue inner: move_task/abort_wait persist across the re-wait)
    elif move_task in done:      -> apply move (below), break inner
    else:                        -> deadline: flag on time (D7 insufficient check), break outer
# after a move applies:
#   - implicit decline: if live.pending_draw_offer == opponent(color): clear it (D6)
#   - piggyback: if seat._offer_draw: live.pending_draw_offer = color
#   - board.push; outcome = board.outcome(claim_draw=True); terminal? -> result/termination
```

Key invariants: `move_task` and `abort_wait` are **persistent** across inner re-waits (recreated only
when a new turn starts); only `ctrl_task` is recreated each drain. Handling a `draw_offer` never
cancels `move_task`, so the mover's think is uninterrupted — the offer shows on the opponent's next
`your_turn` (D6). The clock is charged from `t0` to move-arrival exactly as today (control drains don't
add clock time to the mover — `charge` uses `loop.time()-t0` at move receipt).

### Rating finalize (D-f / D-g / D-h) — the design
```python
# game/ratings.py  (pure)
def expected_score(rating: int, opp: int) -> float: ...          # 1/(1+10**((opp-rating)/400))
def k_factor(games_played: int, *, provisional_k, default_k, provisional_games) -> int: ...
def updated(rating: int, score: float, k: int) -> int: ...       # round(rating + k*(score - expected))

# persistence/finalize.py  (PostgresFinalizer.__call__ -> Optional[FinalizeResult])
#   if result == "aborted": write games row (rating cols NULL); return None
#   else, in ONE session.begin():
#     load white_bot, black_bot (rating, games_played)
#     wc, bc = score(result) for each color            # win=1, draw=0.5, loss=0
#     wa = updated(w.rating, wc, k_factor(w.games_played)); ba = updated(b.rating, bc, ...)
#     write games row incl. white/black_rating_before/after
#     w.rating, b.rating = wa, ba ; w.games_played += 1 ; b.games_played += 1   (per Q3)
#   return FinalizeResult(white=(w0, wa), black=(b0, ba))
```
`run_game` at terminal: `res = await finalizer(...)`; for each seat send `game_over(rating=Rating(
before, after))` from `res` (or the stub when `res is None`). `seat.game_over` gains `before`/`after`
params (drops the captured-`self.rating` stub).

## Project layout (changes this slice)
```
server/engine_room/
  protocol/messages.py      # + Resign, DrawOffer, DrawAccept (inbound) + parse-map; docstrings
  ws/bot_endpoint.py        # route resign/draw_offer/draw_accept -> game.controls (via active index)
  game/
    game.py                 # + Game.controls queue; LiveState.pending_draw_offer; resume_payload flag
    worker.py               # control drain in the per-turn wait; offer lifecycle; claim_draw=True;
                            #   D7 timeout rule; pass real (before,after) to seat.game_over
    seat.py                 # WsSeat: stash _offer_draw; game_over(before,after); your_turn offer flag
    ratings.py              # NEW — pure Elo (expected/k_factor/updated)
  persistence/
    models.py               # + games rating cols; bots.games_played
    finalize.py             # compute+persist Elo in one txn; return FinalizeResult
  config.py                 # + ER_ELO_* knobs
  alembic/versions/0003_*.py  # NEW migration (first since 0002)
# no frontend change (outcomes/ratings are bot-facing; SSE game_over unchanged — Q6)
```

## Affordance → module map
| Affordance | Module | Notes |
|-----------|--------|-------|
| Resign → game_over (N5) | `ws/bot_endpoint.py` + `game/worker.py` | control channel; opponent wins, `resignation` (D-a). |
| Draw offer/accept → agreement (N5, D6) | `game/worker.py` + `game/seat.py` + `game/game.py` | `pending_draw_offer` lifecycle; `opponent_draw_offer` surfaced (D-b/D-c). |
| Auto-draws no-claim (D8) | `game/worker.py` | `board.outcome(claim_draw=True)` (D-d). |
| Timeout vs insufficient (D7) | `game/worker.py` | `has_insufficient_material(winner)` → draw (D-e). |
| Elo math (N8) | `game/ratings.py` | pure; unit-tested table (D-f). |
| Atomic rating write (ADR-0025 #5) | `persistence/finalize.py` + `models.py` | one txn: games cols + `bots.rating`/`games_played` (D-g). |
| Real `game_over.rating` | `game/worker.py` + `game/seat.py` | send persisted `(before, after)`; aborted → none (D-g/D-h). |
| Rating schema | `alembic/versions/0003_*.py` | 4 games cols + `bots.games_played` (Q2). |
| Elo config knobs | `config.py` | `ER_ELO_*` (Q1). |

## Key contracts
```python
# protocol/messages.py  (inbound; add all three to _CLIENT_MODELS)
class Resign(BaseModel):     type: Literal["resign"];      game_id: str
class DrawOffer(BaseModel):  type: Literal["draw_offer"];  game_id: str
class DrawAccept(BaseModel): type: Literal["draw_accept"]; game_id: str

# game/game.py
@dataclass
class LiveState:
    ...                                          # existing
    pending_draw_offer: Optional[str] = None     # "white"|"black" — the OFFERER's color (D-c)
@dataclass
class Game:
    ...                                          # existing
    controls: asyncio.Queue = field(default_factory=asyncio.Queue)  # (color, msg) (D-a)

# game/ratings.py  (pure)
def expected_score(rating: int, opp: int) -> float: ...
def k_factor(games_played: int, *, provisional_k=32, default_k=16, provisional_games=30) -> int: ...
def updated(rating: int, score: float, k: int) -> int: ...

# persistence/finalize.py
@dataclass
class FinalizeResult:
    white: tuple[int, int]   # (before, after)
    black: tuple[int, int]
class PostgresFinalizer:
    async def __call__(self, game, result, termination, final_fen, pgn) -> "FinalizeResult | None": ...

# game/seat.py
class WsSeat:
    async def game_over(self, result, termination, final_fen, pgn,
                        rating_before: int | None = None, rating_after: int | None = None) -> None: ...
```

## Build sub-steps (order within V5) — each ends demoable/testable
1. **Protocol + config + pure ratings.** `Resign`/`DrawOffer`/`DrawAccept` models + parse-map;
   `ER_ELO_*` settings; `game/ratings.py`. **Checkpoint:** unit — parse the three controls; a rating
   table (symmetric ±, provisional K vs default K, draw = half-K move) asserts `updated`/`k_factor`.
2. **Schema migration 0003.** `models.py` (4 `games` rating cols nullable; `bots.games_played`) +
   Alembic `0003`. **Checkpoint:** integration — `alembic upgrade head` then downgrade; a smoke row
   with rating cols round-trips.
3. **Worker terminals: resign / draw / auto-draw / D7 (rating still stubbed).** `game.controls` +
   endpoint routing; the control drain; `pending_draw_offer` lifecycle + `opponent_draw_offer`
   surfacing; `claim_draw=True`; timeout-insufficient. **Checkpoint:** unit (scripted seats/controls)
   — resign → opponent wins/`resignation`; offer+accept → `draw`/`agreement`; a move implicitly
   declines a standing offer; threefold/fifty auto-draw; timeout vs lone king → `draw`/
   `insufficient_material`. WS-seam: a bot that sends `resign` gets `game_over`; the opponent too.
4. **Real Elo in finalize + game_over.** `FinalizeResult`; finalizer computes/persists in one txn +
   updates `bots.rating`/`games_played`; `run_game` passes persisted `(before, after)` to
   `seat.game_over`; aborted → no rating. **Checkpoint:** integration (real DB) — two bots play to a
   decisive result; assert both `bots.rating` moved by the expected Elo delta, `games.*_rating_*`
   columns were written, and it all happened in one txn (winner up, loser down, sum≈conserved). An
   aborted game writes NULL rating cols and both `game_over`s omit `rating`.
5. **Docs + cleanup + demo.** CLAUDE.md V5 → ✅; slices.md V5 row + completion note; PROTOCOL §6/§7/§8
   marked *implemented in V5*; ADR-0008/0011/0016 D6-D8 realized-in-V5 notes; this plan's "deviations
   as built" + "open items resolved/carried". Demo: a bot that resigns, and two bots whose ratings
   visibly change (`make demo` / `make dev` + `make bot`). Full gate green; PR finalized.

## Tests (at the seams — mirrors V1–V4 layering)
- **Unit (`tests/unit/`, no infra):**
  - `ratings.py` table: expected-score symmetry; a 1200-vs-1200 win → +16/−16 (default K) and
    +16/... provisional cases; draw between equals → no change; rounding.
  - Worker terminals with scripted `HouseSeat`-like seats + a pre-loaded `game.controls`: resign,
    offer→accept (agreement), move-declines-offer, `claim_draw` threefold/fifty, D7 timeout-vs-lone-king.
  - Message parse for the three controls; `opponent_draw_offer` reflected in `your_turn`/`resume_payload`.
- **Integration (`tests/integration/`, live uvicorn + testcontainers Postgres):**
  - **Resign WS seam:** two bots (or bot-vs-greeter); one sends `resign`; both get `game_over`
    (opponent wins, `resignation`), with real `rating`.
  - **Draw agreement WS seam:** one offers (`offer_draw` on a move, or `draw_offer`), the other
    `draw_accept`s on its turn → both get `draw`/`agreement`.
  - **Real DB ratings (ADR-0025 #5):** a decisive game moves both `bots.rating`, writes the four
    `games` rating columns, and increments `games_played` — asserted after finalize; an **aborted**
    game leaves rating cols NULL and ratings unchanged.
- **Seam reuse:** extend `tests/support/fake_client.py` — `resign()`, `draw_offer()`, `draw_accept()`,
  and a `move(offer_draw=True)` variant; reuse `live_server(...)` + `matcher_kwargs`/`hb_kwargs` and
  the `FakeBotAuthenticator`/multi-bot helpers.

## Out of scope (pinned to the slice that proves it)
Dashboard / lobby / catch-up / replay / rating display in the UI / ambient pool-resident house bots
→ **V6** · packaged SDK / UCI → **V7** · per-time-control ratings, rating decay, leaderboards,
anti-farm cooldowns / rate limits (ADR-0019) → **post-MVP / V-later** · Redis-backed live state →
scale-out. **No draw-claim protocol** (D8 — the server auto-draws; bots never claim).

## Open items (to carry)
- **O-1 (Q4):** a standalone `draw_offer` sent while the opponent is already mid-think surfaces on the
  *following* `your_turn`, not the current one (we don't re-send `your_turn` mid-turn). Matches D6's
  "next your_turn"; tighten only if a bot's offer UX needs immediacy.
- **O-2 (Q3):** whether house games rate the house bot is a config/scope call (see Q3); if "rate
  both", the house rating drifts — harmless at MVP (house is not on a leaderboard until V6).
- **O-3 (V3 O-3 / Q5):** anti-rematch still records last-opponent at pairing, not FINISHED. Deferred.
- **O-4:** `bots.games_played` starts counting at V5; pre-V5 games don't backfill the provisional
  counter. Acceptable (provisional K just applies to a bot's first 30 *post-V5* rated games).
- **O-5 (resume mid-game rating):** `resume_payload` has no rating block (a running game has no result
  yet) — unchanged; rating only appears in `game_over`.
</content>
</invoke>
