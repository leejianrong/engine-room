---
shaping: true
---

# V3 Plan — Real matchmaking

**Status: ✅ COMPLETE (2026-07-09).** Built in 6 sub-steps on `feat/v3-matchmaking`; the four
open decisions (D-i … D-iv) were confirmed by the owner and are pinned below. `AlwaysPairQueue` is
replaced by an Elo widening-window matcher behind `MatchmakingQueue`; 3+0 **and** 5+0 pools,
same-owner exclusion, soft anti-rematch, seek TTL/cancel, start-grace reap, async `game_start`, and
an on-demand greeter all land. Ratings stay read-only (updates are V5). No schema change. Unit
tests drive the matcher/pool logic DB-free with an injectable clock; a live-uvicorn two-bot test
covers the WS seam. Full gate green.

Implementation plan for slice **V3** (from Shape A, part A3). Higher levels:
[slices.md](slices.md) (V3 row), [shaping.md](shaping.md) (R's, Shape A, A3 thickening row).
Mirrors the format of [V2-plan.md](V2-plan.md). Ground truth remains the ADRs + [PROTOCOL.md](../design/PROTOCOL.md);
where this plan and the docs disagree, the code wins and the docs get updated (CLAUDE.md).

## Goal (definition of done)
Two **real** user bots that seek the same time-control pool are **matched to each other by Elo
proximity** (not to the house bot), play a full game, and finalize as today. **Same-owner** bots
are **never paired** with each other (ADR-0016 H5). A bot that **seeks alone** with no eligible
opponent receives `seek_ended {reason:"expired"}` when its **TTL** elapses (ADR-0016 E8), and a bot
can withdraw early with `seek_cancel` → `seek_ended {reason:"cancelled"}`. The **5+0** pool exists
alongside **3+0**. `game_start` is now **asynchronous** (seek → `seek_ack` immediately; `game_start`
arrives later when the matcher pairs), replacing V1/V2's synchronous always-pair. All of this lives
behind the existing `MatchmakingQueue` interface (R6) so a Redis impl can swap in later; it is
single-process / in-memory (R5). **Rating *updates* on FINISHED games stay V5** — V3 reads each
bot's existing rating (bots default to 1200 from V2) but never writes it.

## What thickens (A3 → V3)
Per [shaping.md A2–A7 table](shaping.md#a2a7--thickening-breadboarded-per-slice-in-the-slices-doc):
> N3 always-pair → Elo pools behind `MatchmakingQueue`, same-owner exclusion (house exempt), seek
> TTL/expiry, anti-rematch, start-grace→ABORTED.

No new *subsystems*. V3 replaces **N3** (`AlwaysPairQueue`) with an Elo-pool matcher behind the same
`MatchmakingQueue` Protocol, and extends **N2** (the seek handler) with `seek_cancel`/`seek_ended`
and asynchronous `game_start` delivery. N4 (house bot), N5–N10 (game loop, clock, pubsub, SSE,
finalize) are untouched except that game launch (`game_start` fan-out + `run_game` spawn) moves out
of the WS endpoint into a small injected launcher shared by the matcher.

## Build-time decisions

### Pinned (rationale below; open to correction)
| # | Decision | Rationale |
|---|----------|-----------|
| D-a | **No schema change / no Alembic migration.** Matcher state (pools, tickets, anti-rematch memory) is **in-memory, single-process** (R5, ADR-0020/0025 #2). Ratings already persist on `bots.rating` (V2). | V3 reads ratings, writes none; nothing durable is added. Keeps the slice thin and reversible. |
| D-b | **Keep the `MatchmakingQueue` Protocol** (`seek`/`cancel`) and **extend it** with `start()`/`stop()` lifecycle for the background matcher task. `seek()` now enrolls a ticket and returns `PairResult(seek_id, game=None)` — **always async** (no inline game). | R6: the WS endpoint keeps calling `queue.seek(...)`/`queue.cancel(...)`; only the impl changes. A Redis-backed matcher swaps in behind the same interface. |
| D-c | **Extract a `GameLauncher` seam** (injected, mirrors the `finalizer` DI): `async launch(game)` sends `game_start` to each live human seat and spawns `run_game(game, pubsub, finalizer)`, tracking the task. The matcher calls it; the WS endpoint no longer spawns games. | The "start a game + notify both bots" logic must run from the **matcher** now (it owns pairing), and be reusable by the house-fallback path. Keeps `bot_endpoint` a pure protocol handler. Unit-testable with a fake launcher. |
| D-d | **Injectable monotonic clock** (`now: Callable[[], float]`, default `time.monotonic`) on the matcher. | Window-widening and TTL are time-driven; a fake clock makes them deterministic in unit tests **without sleeping** (the flakiness trap). |
| D-e | **Tunable numbers live in `config.py`** (`Settings`) with `ER_MM_*` env overrides; the matcher takes them as constructor args (defaults from settings). | Tests construct a matcher with tiny TTL/tick/window values directly; prod reads env. Mirrors how `cors_allow_origins`/secrets are configured. |
| D-f | **Anti-rematch "immediate previous opponent" recorded at pairing time**, in an in-memory `dict[bot_id, bot_id]`. Soft exclusion (E5): skip the previous opponent **only while another eligible opponent exists**; the exclusion lifts once the window uncaps (≥60s wait). | Single-process, cheap, matches ADR-0016 E5's refinement. "At pairing" (the pair is about to play → they are each other's most recent opponent) is the MVP reading; refine to "at FINISHED" in V5 when finalization and matcher share more state. |
| D-g | **Start-grace → ABORTED is realized minimally (E7):** at `launch(game)` the matcher checks each human seat's session is still the registry-*current* one. If a paired bot's session vanished between seek and pairing, the game does **not** start (state `aborted`, no `run_game`); the still-present bot's ticket is **re-enrolled** so it can be matched again. | Both bots queued over live Sessions (ADR-0016 E7), so the only real "no-show" is a socket that died in the pairing gap. A full 10s readiness *timer* is heavier than MVP needs (there is no "ready" message in PROTOCOL); flagged thin in Open items. |
| D-h | **MVP scope held:** single process, no Redis; pools **3+0** and **5+0** only (Blitz); ports :8001/:5174/:5433; frontend↔backend CORS. No rate limits / griefing cooldowns (ADR-0019 H2/H3 — need a counter home) this slice. | R5; unchanged from V1/V2. |

### Confirmed 2026-07-08 (the four formerly-open decisions)
| # | Decision | Confirmed choice |
|---|----------|------------------|
| **D-i** | **House-bot presence model** (shapes the "lonely seek expires" demo). | **Two house roles, only the greeter built in V3** (see [House presence](#house-presence-model-d-i) below). **Kind 2 — ephemeral greeter:** an **on-demand house fallback**, per-pool. The **3+0** pool falls back to a house game after a short **solo-wait `H≈3s`** (a lonely newcomer gets a house opponent → ADR-0022 instant-first-game) while two real bots present pair **real-vs-real** before `H` elapses (the Elo demo). The **5+0** pool has **no greeter** → a lonely 5+0 seek expires at TTL (the expiry demo). Greeter is synthesized on demand (no Session; matches today's sessionless house). **Kind 1 — ambient pool-resident house bots** (Elo-matched, keep a live game for spectators) are **designed now but implemented in V6** with the lobby they populate (needs a 2nd house identity + sessionless in-pool tickets + re-enrollment). Recorded as an ADR-0022 addendum. |
| **D-ii** | **Matcher architecture.** | **Background matcher task (asyncio) nudged by seeks**, behind `MatchmakingQueue` (D-b). A single `tick()` pass per pool: expire TTLs → pair eligible reals (closest Elo) → greeter-fallback the aged-out lonely tickets. The loop wakes on an `asyncio.Event` (set by each `seek`/`cancel`) **and** on a short interval so window-widening/TTL fire without new events. `game_start` is **async** (matches the kickoff note). `tick()` is directly callable in unit tests. |
| **D-iii** | **Which E8 numbers to pin now vs defer.** | **Pin (read-only in V3):** window start **±100**, widen **+100 / 10s**, **uncapped after 60s**; ticket TTL **120s**; start-grace **10s**; pair as soon as **≥2 eligible**; soft anti-rematch. Greeter solo-wait `H` **≈ 3s** (new, tunable). **Defer to V5:** K-factor / provisional threshold / any rating *write* (ADR-0011/A5). All values are `ER_MM_*`-tunable (D-e). |
| **D-iv** | **How pairing is exercised at the WS seam + where matcher state lives.** | **Two layers:** (1) **unit** tests drive the matcher/pool logic **directly, DB-free** — fake `Session`s (BotInfo + owner_id) + a fake `GameLauncher` + the injectable clock (D-d); assert closest-Elo pairing, same-owner exclusion, window widening, soft anti-rematch, TTL→`seek_ended`, greeter fallback. (2) **one live-uvicorn integration** test (like `test_v2_ws_live.py`) drives **two real WS bots** end-to-end: matched to each other, plus a same-owner "never paired" case and a lonely-`seek_ended{expired}` case (tiny TTL via D-e). Anti-rematch/same-owner state is **in-memory, single process** (D-a). |

### House presence model (D-i)
Two house roles serve two different needs; V3 builds only the first.

- **Kind 2 — ephemeral greeter (BUILT in V3).** Guarantees a newcomer's near-instant first game
  (ADR-0022) without blocking real-vs-real pairing. It is **not a ticket** in the pool (it has no
  `Session` — it runs in-process, exactly as today's `AlwaysPairQueue` synthesizes a house
  `Participant`). The matcher **synthesizes a greeter opponent on demand** for a ticket that has
  waited alone ≥ `H`. **Per-pool `greeter` config:** **3+0 enabled** (`H≈3s`) so a lonely 3+0 bot
  gets a house game within a few seconds while two real bots present pair with *each other* first
  (they pair on the tick, well before `H`); **5+0 disabled** so a lonely 5+0 seek runs to TTL and
  expires (the expiry demo). Both `ER_MM_*`-tunable, so the deployed default can differ.
- **Kind 1 — ambient pool-resident house bots (DESIGNED, deferred to V6).** House bots that *sit in
  the pool* and are Elo-matched like users — including against each other (house-vs-house) — so the
  spectator **lobby always has a live game** (ADR-0022 never-empty-lobby). This needs a **2nd house
  identity** (today only `bot_house_random` exists), tickets generalized to sessionless in-process
  participants, and a re-enrollment lifecycle. Its payoff is a populated lobby, which does not exist
  until **V6** — so it lands there, alongside the dashboard it feeds. Recorded as an ADR-0022 addendum.

Consequence for V3: with a single house identity and greeter-only, **house-vs-house games are not
produced** this slice; ADR-0022's *instant-first-game* is met, its *never-empty-lobby-with-zero-users*
part is V6. The Elo and expiry demos stay clean because greeters are per-pool and never crowd the
real-vs-real pairing.

## Project layout (additions this slice)
```
server/engine_room/
  matchmaking/
    queue.py          # MatchmakingQueue Protocol (extended: start/stop) + PairResult — KEEP
    ticket.py         # Ticket dataclass (seek_id, session, tc key, rating, enqueued_at)
    pool.py           # per-time-control waiting-ticket collection + eligibility helpers
    elo.py            # rating-window(waited) fn + closest-eligible selection (pure)
    matcher.py        # EloMatchmaker: implements MatchmakingQueue; tick()/loop; greeter fallback
    launcher.py       # GameLauncher (D-c): game_start fan-out + run_game spawn + task refs
  # always_pair removed (queue.py's AlwaysPairQueue deleted); registry/worker/house_bots unchanged
  config.py           # + ER_MM_* knobs (D-e)
  protocol/messages.py# + SeekCancel (inbound), SeekEnded (outbound); parse map updated
  ws/bot_endpoint.py  # seek → seek_ack only (async); handle seek_cancel; no inline game spawn
# no Alembic migration (D-a); no frontend change (matchmaking is bot-facing; lobby UI is V6)
```

## Affordance → module map
| Affordance | Module | Notes |
|-----------|--------|-------|
| N3 matcher (thickened) | `matchmaking/matcher.py` (+ `pool.py`, `elo.py`, `ticket.py`) | Elo pools behind `MatchmakingQueue`; replaces `AlwaysPairQueue`. |
| N2 seek handler (extended) | `ws/bot_endpoint.py` | `seek`→`seek_ack` (async); `seek_cancel`→ `queue.cancel`; matcher delivers `game_start`. |
| Game launch (moved) | `matchmaking/launcher.py` | `game_start` fan-out to live seats + `run_game` spawn + `_running_games` refs (was inline in `bot_endpoint`). |
| Seek TTL / expiry / cancel (E8) | `matchmaking/matcher.py` + `protocol/messages.py` | `seek_ended{expired|cancelled}`. |
| Same-owner exclusion (H5) | `matchmaking/pool.py` (eligibility) | `owner_id` equal & non-null ⇒ ineligible; greeter exempt (never a ticket). |
| Soft anti-rematch (E5) | `matchmaking/matcher.py` | in-memory last-opponent map (D-f). |
| Start-grace → ABORTED (E7) | `matchmaking/launcher.py` / `matcher.py` | liveness check at launch (D-g). |
| Config knobs | `config.py` | `ER_MM_*` (D-e). |

## Key contracts
```python
# matchmaking/queue.py — interface KEPT (R6); impl swaps AlwaysPair → EloMatchmaker
class MatchmakingQueue(Protocol):
    async def seek(self, session: "Session", time_control: TimeControl) -> PairResult: ...
    async def cancel(self, seek_id: str) -> None: ...       # → seek_ended{cancelled}
    async def start(self) -> None: ...                      # spawn the matcher loop (D-b)
    async def stop(self) -> None: ...                       # cancel the loop on shutdown
# PairResult.game is now always None (async game_start); field kept for interface stability.

# matchmaking/ticket.py
@dataclass
class Ticket:
    seek_id: str
    session: "Session"        # → bot identity (.bot.id, .bot.rating) + owner
    owner_id: str | None      # from the bot; None for house (house is never a ticket)
    tc_key: str               # "180+0" / "300+0"
    rating: int
    enqueued_at: float        # matcher clock (D-d)

# matchmaking/elo.py — pure, unit-tested
def rating_window(waited_s: float, *, start=100, step=100, step_s=10, uncap_after_s=60) -> float:
    # ±100 to start, +100 every 10s, +inf (uncapped) after 60s   → returns float('inf')
def eligible(a: Ticket, b: Ticket, now: float) -> bool:
    # same pool (caller-guaranteed) · owners differ or a NULL · |ra-rb| <= max(window_a, window_b)
def best_opponent(t: Ticket, pool: list[Ticket], now, excluded: set[str]) -> Ticket | None:
    # closest |Δrating| among eligible; tie-break oldest enqueued_at; honor soft anti-rematch

# matchmaking/launcher.py (D-c) — injected like finalizer
class GameLauncher(Protocol):
    async def launch(self, game: Game) -> None: ...   # game_start to live seats + spawn run_game
```

## Matcher mechanics (`tick()` — one pass, called by the loop and by tests)
Per pool, in order:
1. **Reap** tickets whose `session` is no longer `session_registry.current(bot_id)` (disconnected /
   replaced) — drop silently (the endpoint's disconnect path also `cancel`s).
2. ✅ **Expire** tickets with `now - enqueued_at ≥ TTL` → send `seek_ended{expired}` on that session,
   remove.
3. ✅ **Pair reals**: process oldest-first; for each unpaired ticket `t`, `best_opponent(t, pool, now,
   excluded=antirematch(t))`; if found, `registry.create_game(white, black, tc)` (color by coin/oldest
   = White), record last-opponent (D-f), `await launcher.launch(game)`, remove both. Repeat until no
   pair.
4. ✅ **Greeter fallback** (if pool `greeter` enabled, D-i): any ticket with `now - enqueued_at ≥ H`
   and still unpaired → create a game vs a synthesized house `Participant`, `launcher.launch`, remove.

`seek()` enrolls the ticket, `event.set()` (nudge the loop), returns `PairResult(seek_id)`.
`cancel(seek_id)` removes the ticket if present and sends `seek_ended{cancelled}`.
The loop: `await wait_for(event.wait(), timeout=tick_interval)` → `tick()` for all pools → repeat.

## Protocol additions (`protocol/messages.py`, mirrors PROTOCOL.md §5)
```python
class SeekCancel(BaseModel):      # inbound
    type: Literal["seek_cancel"]
    seek_id: str
class SeekEnded(BaseModel):       # outbound
    type: Literal["seek_ended"] = "seek_ended"
    seek_id: str
    reason: str                   # "cancelled" | "expired"
# add "seek_cancel": SeekCancel to _CLIENT_MODELS
```

## Build sub-steps (order within V3) — all ✅ done
> Deviations from the plan as built: (a) the affected V1/V2 tests were migrated in the **same**
> commit as the create_app swap (sub-step 5), not a trailing sub-step 6, so every commit kept the
> gate green — done via an `always_pair=True` escape hatch on `create_app`/`connect` rather than
> rewriting each game-loop test onto the async matcher. (b) Start-grace (D-g) is realized as a
> **reap-before-pair** in `tick()` step 1 (a ticket whose session vanished is dropped before it can
> be paired; the survivor stays enrolled) rather than an abort-at-launch — simpler and it needs no
> ABORTED game. (c) `owner_id` reaches the matcher via a **wire-excluded** `BotInfo.owner_id` field
> (no authenticator return-type change), keeping ownership off the wire (H5).

1. ✅ **Config knobs + protocol messages.** Add `ER_MM_*` settings (D-e); `SeekCancel`/`SeekEnded` +
   parse-map entry. **Checkpoint:** unit — parse `seek_cancel`; settings default/override.
2. **Pool + Elo eligibility (pure).** `ticket.py`, `pool.py`, `elo.py`. **Checkpoint:** unit —
   `rating_window` schedule; `eligible` (same-owner, within/without window); `best_opponent`
   closest-Δ + tie-break + anti-rematch exclusion. All with an explicit `now`.
3. **GameLauncher (D-c).** Extract `game_start` fan-out + `run_game` spawn from `bot_endpoint` into
   `launcher.py`; wire into `create_app`. **Checkpoint:** existing V1 game-loop/pairing tests pass
   against the launcher path (some updated per sub-step 6). Unit — launcher sends `game_start` to a
   fake session and spawns the game.
4. **EloMatchmaker + loop.** `matcher.py` implementing `MatchmakingQueue` (`seek`/`cancel`/`start`/
   `stop`) + `tick()`; greeter fallback (D-i); start-grace liveness check (D-g). Wire into `create_app`
   (lifespan start/stop) replacing `AlwaysPairQueue`. **Checkpoint:** unit — drive `tick()` directly:
   two reals pair by Elo; same-owner never pair; far ratings pair only after widening (advance fake
   clock); TTL→`seek_ended{expired}`; `cancel`→`seek_ended{cancelled}`; greeter fallback after `H`.
5. ✅ **WS endpoint async seek + seek_cancel.** `seek`→`seek_ack` only; route `seek_cancel`→`cancel`;
   remove inline game spawn; matcher/launcher deliver `game_start`. Teach `fake_client.py`
   `seek_cancel`/`expect seek_ended`, and a two-bot live helper. **Checkpoint:** live-uvicorn
   integration (D-iv) — two real bots matched to each other + play out; same-owner pair never matched;
   lonely seek → `seek_ended{expired}` (tiny TTL).
6. ✅ **Migrate V1/V2 tests to async game_start + docs/cleanup.** Update `test_v1_pairing.py`,
   `test_v1_spectate_live.py`, `test_v1_finalize.py`, and any handshake test expecting instant
   `game_start` (now: seek two bots / await fallback). Update CLAUDE.md build-status (V3 ✅), slices.md
   V3 row + breadboard, this plan's status → done; note the ADR-0022 scope in an ADR addendum. ruff
   clean; full gate green; finalize the PR.

## Tests (at the seams — mirrors V1/V2 layering)
- **Unit (`tests/unit/`, no infra):** pure Elo/pool functions (sub-step 2); matcher `tick()` behaviors
  with fake sessions + fake launcher + fake clock (sub-step 4) — pairing, same-owner, widening,
  anti-rematch, TTL, cancel, greeter fallback; launcher fan-out (sub-step 3); `seek_cancel` parse.
- **Integration (`tests/integration/`, live uvicorn like `test_v2_ws_live.py`):** two real WS bots
  matched to each other and playing out; same-owner two-bot "never paired"; lonely `seek_ended{expired}`
  with a tiny TTL. (A real-DB variant can reuse the V2 authenticator to prove ratings are read from
  Postgres, optional.)
- **Seam reuse:** extend `tests/support/fake_client.py` — `seek_cancel(seek_id)`, `expect("seek_ended")`,
  and a two-bot live harness helper alongside the existing `connect(...)`.

## Out of scope (pinned to the slice that proves it)
Reconnect-resume (`welcome.active_game`) / `ply`-idempotency / heartbeat / illegal-move forfeit → V4 ·
resign/draw/auto-draw / **real Elo rating updates + K-factor** → V5 (ADR-0011/A5) · dashboard / lobby /
catch-up / replay / bot-management UI → V6 · packaged SDK / UCI → V7 · rate limits & griefing cooldowns
(ADR-0019 H2/H3) → V-later · ambient pool-resident house bots (Kind 1) / 2nd house identity /
house-vs-house / never-empty-lobby → V6 · per-time-control ratings / Redis matcher → post-MVP scale-out.

## Open items (resolved / carried)
- **O-1 (D-i):** ✅ resolved — the two-house-role model (greeter now, ambient V6) was confirmed by the owner.
- **O-2 (D-g):** ✅ realized as a **reap-before-pair** in `tick()` (a ticket whose live session vanished
  is dropped before it can be paired; the survivor stays enrolled), not a launch-time abort or a 10s
  readiness timer — there is no "ready" message in PROTOCOL and both bots queue over live Sessions.
  A full readiness timer is deferred (V4 resilience, if ever needed).
- **O-3 (D-f):** carried — anti-rematch "previous opponent" is recorded **at pairing** (not at FINISHED)
  for MVP simplicity; refine in V5 when finalization state is shared with the matcher.
- **O-4 (ADR-0022):** ✅ done — ADR-0022 gained a two-house-role addendum (greeter V3 / ambient V6).
- **O-5:** ✅ done — the V1/V2 tests that assumed *synchronous* game_start-vs-house use the
  `always_pair=True` escape hatch (game-loop/pairing) or a fast greeter (live SSE); the async
  `game_start` switch is otherwise a deliberate, owner-noted change proven by the live matcher test.
