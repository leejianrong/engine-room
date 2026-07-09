---
shaping: true
---

# V7 Plan — Hero onboarding: packaged `chessroom` SDK + `uv` quickstart + UCI bridge

**Status: 📝 PLAN DRAFT (2026-07-09) — awaiting owner confirmation of the to-confirm decisions
before implementation.** Built on `feat/v7-sdk` off merged V6 (`4600a7a`, PR #13; V6 was merged to
main first so V7 can verify its end-to-end demo against the real dashboard). Ground truth is the
ADRs + [PROTOCOL.md](../design/PROTOCOL.md); where this plan and the docs disagree, **the code wins
and the docs get updated** (this slice is expected to record real drift against ADR-0021/0022/0024 —
see D-a).

Implementation plan for slice **V7** (Shape A, part A7). Higher levels: [slices.md](slices.md) (V7
row), [shaping.md](shaping.md) (Shape A, A7 in the A2–A7 thickening row). This is the final MVP
slice — it turns the wire client from a **test harness** into a **packaged SDK** and makes the
ADR-0023 hero flow ("zero → live watchable game in minutes, no protocol plumbing") real.

## Goal (definition of done)
> A newcomer `git clone`s the quickstart, `uv sync`s, pastes their `crbk_` key into `.env`, runs
> `uv run python random_bot.py`, and within minutes their bot is matched and playing a full 3+0
> game — **live on the V6 dashboard**. A UCI user points Stockfish at the platform with one command.

Concretely:
- **`chessroom` SDK** — a `pip`/`uv`-installable package. The user **subclasses `Bot` and implements
  `choose_move(board) -> move`** (board is a `python-chess` `Board`); the SDK owns the WebSocket
  transport, the authenticated handshake, auto-seek/queue, reconnect-resume, `ply`-idempotent
  resends, heartbeat pong, and all protocol (de)serialization (ADR-0021). Config via `CHESSROOM_KEY`
  (+ `CHESSROOM_URL`) env (ADR-0022).
- **Reference bots** — `RandomBot` (hello-world) and `MinimaxBot` (level-2) ship in the SDK; their
  move logic mirrors the server's house bots (ADR-0022 "reference bots double as house bots").
- **UCI bridge** — a `UCIBot` (+ a `chessroom-uci` console entry point) whose `choose_move` delegates
  to a local UCI engine (e.g. Stockfish) via `chess.engine`, entirely client-side (ADR-0021 L2).
- **`uv` quickstart template** — a minimal, ready-to-run `RandomBot` project (`pyproject.toml` +
  `uv.lock` + `random_bot.py` + `.env.example` + README + optional `Dockerfile`) that depends on the
  published SDK, not a vendored copy (ADR-0022 / ADR-0024). Target: `< 20 min` zero-to-first-move.
- **End-to-end smoke realized** — the ADR-0023 flow (real key → SDK `RandomBot` runs → the game
  appears on the V6 lobby → watch it) becomes an actual, runnable check now that V6's dashboard
  exists.

**No schema change, no migration.** V7 adds no columns/tables and no new server behavior — the
protocol (V1–V5) and the spectator surface (V6) are already complete. V7 is a **new client package**
+ its quickstart + a small amount of server-side test/demo glue. The one server-repo touch is
optional dev ergonomics (a `make` target + a contract test).

## What thickens (A7 → V7)
Per [shaping.md A2–A7 table](shaping.md#a2a7--thickening-breadboarded-per-slice-in-the-slices-doc):
> Bot client stub → packaged `chessroom` SDK repo + `uv` quickstart + client-side UCI bridge;
> reference bots become the N4 house bots.

No new *server subsystems*. V7 thickens the **client** end of the wire contract:
- The wire loop that today exists twice as **throwaway clients** (`devtools/demo_bot.py`,
  `tests/support/fake_client.py`) is **extracted and hardened** into a real, reusable, documented SDK
  that hides reconnect/idempotency/heartbeat behind `choose_move`.
- The N4 house bots' *move logic* becomes the SDK's reference bots (mirrored, not shared-imported —
  the decoupling in ADR-0021 forbids the server importing the SDK; see O-1).
- The ADR-0023 end-to-end smoke (which V6's `frontend/e2e/smoke.spec.ts` stood up for
  dashboard→watch→replay) is **completed** with the missing first leg: a real SDK bot creating the
  game that gets watched.

## The core problem (why this slice is real work)
1. **A public contract, not shared code (ADR-0021 decoupling).** The SDK must implement PROTOCOL.md
   from the *spec*, never by importing `engine_room`. The two existing clients cheat: `fake_client`
   imports `engine_room.protocol.messages.BotInfo` and runs in-process; `demo_bot` lives inside the
   server package. Extracting a clean SDK means re-deriving the message shapes from the spec and
   proving (by an import-boundary test) the package has zero server imports.
2. **Hiding resilience behind one method.** A beginner writes only `choose_move`. Everything the
   protocol demands to *stay alive* — pong on `ping` (§10), resend the same `move` on a missing
   `move_ack` and after reconnect (§9), re-open + resume from `welcome.active_game` (§8), skip stale
   `game_over`/`seek_ack` frames (V4 D-vi) — must be handled invisibly and correctly by the SDK's
   run loop. `demo_bot.py` already does all of this; V7 turns that battle-tested logic into a library
   with a clean surface and real tests, not a demo script.
3. **Testing a client without shipping the server to it.** The SDK is decoupled, but its only honest
   test is *against the real server*. V7 must reuse the existing live-uvicorn + testcontainers seam
   to run the **packaged** SDK against a live game to `game_over`, while keeping a fast, infra-free
   unit layer (protocol codec + run-loop logic over a fake transport).
4. **The repo-layout fork.** ADR-0021/0022 specify *separate repos*; but V7 is a slice **in this
   monorepo** with CI-as-gate, `make` targets, and layered test seams that all live here. Landing a
   testable, demoable slice now vs. honoring the literal separate-repo end-state is a real tension
   (D-a / the biggest to-confirm decision).

## Build-time decisions

### Pinned (low-fork; rationale below)
| # | Decision | Rationale |
|---|----------|-----------|
| P-a | **Extract the SDK wire loop FROM `devtools/demo_bot.py`, not a rewrite.** `demo_bot` is already a full, correct client: hello, async `game_start`, `your_turn`→move→`move_ack`, heartbeat pong, reconnect-resume, resign, stale-frame skipping. The SDK is that loop refactored into a `Bot` base class + a `Connection`/run loop, with `choose_move` as the one user hook. | The resilience logic is subtle (§8/§9/§10) and already proven by the V4/V5 demos. Reinventing it invites regressions. |
| P-b | **`Bot` base class, `choose_move(board: chess.Board) -> chess.Move \| str` is the sole required override.** The SDK constructs the `Board` from the `your_turn.fen` each turn (PROTOCOL B5: full FEN every turn → stateless bot). Return a `chess.Move` or a UCI string. `python-chess` is the board type (ADR-0021). | Matches ADR-0021 exactly; FEN-per-turn means the SDK never has to sync a board (no client board-sync bugs). |
| P-c | **`bot.run()` is the entry point.** It connects (auth via `CHESSROOM_KEY`), sends `hello`, resumes an `active_game` if present else auto-seeks the configured time control, then plays each game to `game_over`; `run(loop=True)` keeps seeking new games (the house-bot / demo pattern). Blocking, `asyncio` under the hood; a sync `bot.run()` wrapper hides the event loop from beginners. | The hero path is "write `choose_move`, call `run()`, watch." No asyncio knowledge required for the RandomBot flow. |
| P-d | **Config by env, override by kwarg.** `CHESSROOM_KEY` (required, ADR-0022) and `CHESSROOM_URL` (default the deployed `wss://engine-room.fly.dev/api/bot/v1`; override to `ws://localhost:8001/...` for local dev) read from the environment, overridable via `Bot(key=..., url=...)`. Time control via `Bot(time_control=(180, 0))` (default 3+0). | Env-first matches the quickstart `.env` flow; kwargs keep it testable and let local dev point at `:8001`. Defaulting to the live platform means a newcomer with just a key is playing on the real dashboard. |
| P-e | **`uv` + `pyproject.toml` + `uv.lock`; `hatchling` build backend; deps = `websockets`, `chess`; `requires-python >=3.10`.** Mirrors `server/pyproject.toml` conventions (ADR-0024). No `engine_room` dependency (enforced by O-boundary test). | ADR-0024 pins `uv`; matching the server's build backend/toolchain keeps one mental model. The SDK's runtime deps are exactly what `demo_bot` uses (`websockets`, `chess`). |
| P-f | **Reconnect / `ply`-idempotency / heartbeat are hidden by the run loop, not exposed.** The SDK pongs pings, resends the same `move` on a missing `move_ack` or after a reconnect (same `game_id`+`ply`+`uci`, safe per §9), re-opens on `ConnectionClosed` and resumes from `welcome.active_game` (§8), and ignores stale `seek_ack`/`game_over` from a prior game (V4 D-vi). | This is the whole point of an SDK (ADR-0021): the beginner's `choose_move` never sees a disconnect. Logic ported verbatim from `demo_bot._reconnect_resume` / `_next`. |
| P-g | **No server schema/behavior change; no migration.** V7 adds a client package + quickstart + tests/demo glue only. | The protocol and spectator surfaces are complete (V1–V6). The house bots are already seeded (V6 `0004`). |
| P-h | **MVP scope held:** Python SDK only (ADR-0021: other languages deferred); Blitz only (3+0/5+0); the UCI bridge is *secondary polish* (ADR-0023). Resign/draw exposed minimally (P-i in to-confirm). | R5 / ADR-0023 scope, unchanged from V1–V6. |

### To confirm (owner sign-off before implementation — ★ = my recommendation)

| # | Question | Options & recommendation |
|---|----------|--------------------------|
| **Q1 — Repo layout (THE big fork)** | ADR-0021/0022 say *separate repos* for the SDK and the quickstart. Do we create new repo(s), or land the SDK as a package **in this monorepo**? | **★ (A) Monorepo package now, extract-on-publish later.** SDK at `sdk/chessroom/` (own `pyproject.toml`, **zero `engine_room` imports**, enforced by a boundary test), quickstart at `sdk/quickstart/`. The quickstart installs the SDK by **path/git** dependency during V7. This lets V7 land as a *real, CI-gated, demoable slice now* — `make`, testcontainers, and the Playwright smoke all already live here and reach it. Honors the decoupling that matters (no shared server code) while deferring the *literal* separate-repo + PyPI end-state to a tracked follow-up (git-subtree split + PyPI publish — needs an owner PyPI account/token, an owner action). **Updates ADR-0021/0024 to record "monorepo-package-first, extract-on-publish."** ⟶ (B) Two new repos (`chessroom` + `chessroom-quickstart`) now — matches the ADRs literally, but cross-repo CI + publishing + install-from-git before V7 can prove itself; the end-to-end smoke can't be one CI job in this repo. ⟶ (C) One new repo (SDK, quickstart as `examples/` subdir). Middle ground; still cross-repo. **Trade-off axis:** *install* — path/git (A, no publish) vs. PyPI `pip install chessroom` (the literal ADR-0022 promise, needs a publish step + account). I recommend building on path/git and treating PyPI publish as an explicit, separate follow-up so "pip-installable" is *proven buildable* without blocking the slice on registry credentials. |
| **Q2 — SDK surface breadth** | Beyond `choose_move`, what does v1 expose? | **★ Minimal + optional lifecycle hooks.** Required: `choose_move`. Optional overridable no-op hooks: `on_game_start(info)`, `on_game_over(result)`. The SDK auto-declines draws (a move implicitly declines, §7) and never offers/claims. Everything else (reconnect/heartbeat/idempotency) stays hidden (P-f). ⟶ Alt: also expose `on_your_turn(state)` for full control (power users) — defer to v1.x. |
| **Q3 — Resign / draw in the SDK** | The protocol has resign + draw offer/accept (§7). Expose in v1? | **★ Yes, minimally:** `choose_move` may return the sentinel `chessroom.RESIGN`, and `state.opponent_draw_offer` is surfaced so a bot can return `chessroom.ACCEPT_DRAW`; offering a draw is a `Bot(offer_draw=…)`/return-tuple extension deferred to v1.x. Keeps the hero RandomBot to "return a move" while making resign/accept reachable (the `demo_bot --resign-after` behavior). ⟶ Alt: omit entirely from v1 (RandomBot never resigns) — simplest, but loses a real protocol capability the demo already shows. |
| **Q4 — UCI bridge packaging** | Ship in the SDK or as a separate entry point/package? | **★ In the SDK**, as `chessroom.uci.UCIBot` + a `chessroom-uci` console script (`[project.scripts]`). Delegates to `chess.engine.SimpleEngine.popen_uci(<engine path>)`; config = engine path + think time/depth. Stockfish is **not bundled** (user supplies a binary). Secondary polish (ADR-0023). ⟶ Alt: separate `chessroom-uci` package — more release surface for a near-free feature `python-chess` already enables. |
| **Q5 — Quickstart contents & the "reference bots = house bots" reconciliation** | What's in the template, and how literally do the SDK reference bots "double as" the server house bots? | **★ Quickstart = a learning-shaped `RandomBot` file** (subclass `Bot`, ~10 lines) even though the SDK ships `RandomBot` — the point is to *show the pattern*. Plus `pyproject.toml`/`uv.lock`, `.env.example` (`CHESSROOM_KEY=`), README (the <20-min path), optional `Dockerfile` (ADR-0024). **Reference-bots reconciliation:** the SDK's `RandomBot`/`MinimaxBot` **mirror** the server house bots' logic (both trivially wrap `python-chess` / the existing `game/minimax.py`) but are **not shared-imported** — the server keeps its in-process `game/house_bots.py` (sessionless, no socket) and must not import the SDK (ADR-0021 decoupling). Documented as O-1, not a code merge. ⟶ Alt: make `game/house_bots.py` import `chessroom` — **rejected**, violates the decoupling ADR. |
| **Q6 — Testing depth & the end-to-end smoke** | How do we test the packaged SDK, and do we finally wire the ADR-0023 signup→SDK→watch smoke? | **★ Three layers:** (1) **SDK unit** (`sdk/chessroom/tests/`, no infra) — protocol codec + run-loop logic over a *fake in-memory transport* (scripted server frames), incl. reconnect/resend/pong; fast, in the gate. (2) **Contract/integration** (`server/tests/integration/`, live-uvicorn + testcontainers) — the **packaged** SDK's `RandomBot` plays a real game vs the greeter to `game_over`; a simulated mid-game drop resumes and finishes; an import-boundary test asserts `chessroom` imports no `engine_room`. (3) **End-to-end** — extend V6's Playwright smoke (or a thin integration variant): start an SDK `RandomBot`, assert its game appears in `GET /api/games` / the lobby and is watchable (the ADR-0023 realization). ⟶ Alt: skip layer (3) — but V6 exists precisely to make this meaningful, so I recommend wiring at least the API-level end-to-end assertion. |

---

### SDK shape (P-a/P-b/P-c/P-f) — the design
```python
# chessroom/__init__.py  (public surface)
from chessroom.bot import Bot
from chessroom.bots import RandomBot, MinimaxBot
from chessroom.uci import UCIBot
from chessroom.const import RESIGN, ACCEPT_DRAW

# chessroom/bot.py
class Bot:
    def __init__(self, key=None, url=None, name=None, time_control=(180, 0)): ...
    def choose_move(self, board: chess.Board) -> chess.Move | str: raise NotImplementedError
    def on_game_start(self, info: GameStart) -> None: ...   # optional no-op hook
    def on_game_over(self, result: GameOver) -> None: ...   # optional no-op hook
    def run(self, *, loop: bool = False) -> None:           # sync wrapper over _run()
        asyncio.run(self._run(loop=loop))
    async def _run(self, *, loop): ...   # connect→hello→resume|seek→play→(loop) ; hides §8/§9/§10

# the run loop (ported from demo_bot): pong pings, resend move on missing ack / after reconnect,
# reopen + resume from welcome.active_game, skip stale seek_ack/game_over, call choose_move each turn.
```
```
# quickstart/random_bot.py  (what the newcomer runs)
from chessroom import Bot
import chess, random
class RandomBot(Bot):
    def choose_move(self, board):
        return random.choice(list(board.legal_moves))
if __name__ == "__main__":
    RandomBot().run(loop=True)     # reads CHESSROOM_KEY / CHESSROOM_URL from .env
```

### Newcomer path (ADR-0022, target < 20 min)
```
1. GitHub sign-in → create a bot → copy the crbk_ key (V2 REST; browser or `make mint` locally)
2. git clone <quickstart>  &&  cd quickstart
3. uv sync                                   # installs chessroom (ADR-0024)
4. cp .env.example .env; paste CHESSROOM_KEY  (+ CHESSROOM_URL for local dev)
5. uv run python random_bot.py               # SDK connects, auto-seeks, plays
6. open the dashboard → the game is live in the lobby → watch it (V6)
```

### UCI bridge (Q4) — the design
```python
# chessroom/uci.py
class UCIBot(Bot):
    def __init__(self, engine_path, *, think_time=0.1, **kw):
        super().__init__(**kw); self._engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    def choose_move(self, board):
        return self._engine.play(board, chess.engine.Limit(time=self._think_time)).move
# console: `chessroom-uci --engine /path/to/stockfish [--think-time 0.1]`  (reads CHESSROOM_KEY)
```

## Project layout (changes this slice — assuming Q1 ★ = monorepo package)
```
sdk/
  chessroom/
    pyproject.toml         # NEW — uv/hatchling; deps: websockets, chess; no engine_room dep (P-e)
    uv.lock                # NEW
    README.md              # NEW — SDK usage
    src/chessroom/
      __init__.py          # NEW — public surface (Bot, RandomBot, MinimaxBot, UCIBot, RESIGN, …)
      bot.py               # NEW — Bot base class + run loop (extracted from demo_bot, P-a/P-f)
      connection.py        # NEW — WS connect/hello/reconnect; frame read w/ pong (from demo_bot._next)
      protocol.py          # NEW — message shapes/codec re-derived from PROTOCOL.md (no server import)
      bots.py              # NEW — RandomBot, MinimaxBot reference bots (mirror house logic, O-1)
      uci.py               # NEW — UCIBot + chessroom-uci console entry (Q4)
      const.py             # NEW — RESIGN / ACCEPT_DRAW sentinels; DEFAULT_URL; protocol version
    tests/                 # NEW — SDK unit tests over a fake in-memory transport (Q6 layer 1)
  quickstart/
    pyproject.toml         # NEW — depends on chessroom (path/git, Q1); uv
    uv.lock                # NEW
    random_bot.py          # NEW — the hello-world subclass (Q5)
    .env.example           # NEW — CHESSROOM_KEY= / CHESSROOM_URL=
    README.md              # NEW — the <20-min path
    Dockerfile             # NEW — optional/advanced (ADR-0024)
server/
  tests/integration/
    test_v7_sdk_live.py    # NEW — packaged SDK RandomBot plays vs greeter to game_over; drop→resume;
                           #        import-boundary (no engine_room); game appears in GET /api/games (Q6)
Makefile                   # + `make sdk-bot` (run the quickstart RandomBot vs a running stack)
docs/                      # updated: ADR-0021/0022/0024 (drift), PROTOCOL note, slices/shaping, this plan
# NO server engine_room/ code change; NO alembic migration (P-g)
```

## Affordance → module map
| Affordance | Module | Notes |
|-----------|--------|-------|
| `Bot` base + `choose_move` (ADR-0021 L1) | `sdk/chessroom/src/chessroom/bot.py` | sole user hook; sync `run()` wrapper (P-b/P-c). |
| WS transport + handshake + reconnect (§4/§8) | `chessroom/connection.py` | from `demo_bot._connect`/`_reconnect_resume`/`_next` (P-a/P-f). |
| `ply`-idempotent resends + heartbeat pong (§9/§10) | `chessroom/bot.py` run loop | resend same move on missing ack / after reconnect; pong pings (P-f). |
| Protocol codec (PROTOCOL.md) | `chessroom/protocol.py` | re-derived from the spec; **no `engine_room` import** (P-e, boundary test). |
| Reference bots (ADR-0022) | `chessroom/bots.py` | `RandomBot`/`MinimaxBot` mirror house logic (O-1). |
| UCI bridge (ADR-0021 L2) | `chessroom/uci.py` + `[project.scripts]` | `UCIBot` + `chessroom-uci` (Q4). |
| Config (CHESSROOM_KEY/URL, ADR-0022) | `chessroom/const.py` + `Bot.__init__` | env-first, kwarg override (P-d). |
| Quickstart template (ADR-0022/0024) | `sdk/quickstart/` | clone → uv sync → run (Q5). |
| SDK unit tests | `sdk/chessroom/tests/` | fake in-memory transport (Q6 layer 1). |
| SDK contract / end-to-end | `server/tests/integration/test_v7_sdk_live.py` | live-uvicorn + testcontainers; lobby appearance (Q6 layers 2–3). |
| Dev ergonomics | `Makefile` (`make sdk-bot`) | run the quickstart bot vs `make dev`. |

## Build sub-steps (order within V7) — each ends demoable/testable
1. **SDK skeleton + wire loop (happy path).** `sdk/chessroom/` package (pyproject/uv, `Bot`,
   `connection`, `protocol`, `const`, `RandomBot`); `choose_move` hook; `run()`; connect→hello→seek→
   play→`game_over`. **Checkpoint:** SDK unit — `RandomBot` plays a full game to `game_over` over a
   fake scripted transport; ruff/lint clean; import-boundary test (no `engine_room`).
2. **Resilience hidden by the SDK (§8/§9/§10).** Port reconnect-resume, missing-ack/reconnect resend,
   pong, stale-frame skipping. **Checkpoint:** SDK unit — a scripted drop mid-game → the loop
   reconnects, resends, and finishes; a duplicate `move_ack`/stale `game_over` is ignored.
3. **Contract test against the real server.** Run the **packaged** SDK `RandomBot` against a live
   uvicorn + testcontainers Postgres, playing vs the greeter to a real `game_over`; assert the game
   appears in `GET /api/games`. **Checkpoint:** `server/tests/integration/test_v7_sdk_live.py` green
   (needs Docker).
4. **Resign/draw surface + lifecycle hooks (Q2/Q3).** `RESIGN`/`ACCEPT_DRAW` sentinels; surface
   `opponent_draw_offer`; optional `on_game_start`/`on_game_over`. **Checkpoint:** SDK unit — a bot
   returning `RESIGN` yields a `resign` frame → `game_over{resignation}`; a move implicitly declines a
   standing offer.
5. **UCI bridge (Q4).** `chessroom.uci.UCIBot` + `chessroom-uci` console script. **Checkpoint:** SDK
   unit with a mock engine (no binary needed); an integration run gated on a real engine
   (`skipif` no `stockfish` on PATH).
6. **Quickstart template + `make sdk-bot`.** `sdk/quickstart/` (pyproject/uv, `random_bot.py`,
   `.env.example`, README, optional Dockerfile); a `make sdk-bot` target. **Checkpoint:** manual —
   `make dev` + (in the quickstart) `uv sync && uv run python random_bot.py` (or `make sdk-bot`) plays
   a game that shows up on the dashboard.
7. **End-to-end smoke (ADR-0023).** Extend V6's Playwright smoke (or an integration variant): an SDK
   `RandomBot` creates a game that appears in the lobby and is watchable. **Checkpoint:** the smoke
   passes locally + in CI (the ADR-0023 signup→SDK→watch flow, now real).
8. **Docs + cleanup + demo.** CLAUDE.md V7 → ✅ (+ build-status row: SDK/UCI no longer "separate
   repo — V7"); slices.md V7 row + completion note; ADR-0021/0024 (monorepo-package-first +
   extract-on-publish drift, Q1), ADR-0022 (quickstart realized + reference-bots reconciliation O-1);
   PROTOCOL §13 note (the SDK is the reference conformer); this plan's "deviations as built" +
   "open items resolved/carried". Full fast gate + integration + e2e green; PR finalized.

## Tests (at the seams — mirrors V1–V6 layering)
- **SDK unit (`sdk/chessroom/tests/`, no infra — fake in-memory transport):**
  - Happy path: `RandomBot` plays scripted `your_turn`s to `game_over`; correct `move` frames (right
    `game_id`/`ply`/`uci`).
  - Resilience: pong on `ping`; resend same `move` on a missing `move_ack`; reconnect-resume from a
    scripted `welcome.active_game`; ignore stale `seek_ack`/`game_over` (V4 D-vi); `INVALID_PLY`/dup
    handling per §9.
  - Codec/boundary: message (de)serialization matches PROTOCOL.md; **no `engine_room` import** in the
    package (an AST/import scan).
  - Resign/draw (Q3): `RESIGN`→`resign` frame; `ACCEPT_DRAW` on a standing offer→`draw_accept`.
- **Contract/integration (`server/tests/integration/`, live uvicorn + testcontainers Postgres):**
  - The **packaged** SDK `RandomBot` plays a full game vs the greeter to `game_over`; a mid-game
    socket drop resumes and finishes (real server, real clock).
  - The SDK bot's game appears in `GET /api/games` (the lobby) with its name/rating.
  - UCI bridge live run gated on a real engine binary (`skipif` no `stockfish`).
- **End-to-end (Q6 layer 3):** extend `frontend/e2e/smoke.spec.ts` (or a thin integration variant) so
  an SDK `RandomBot` supplies the live game the dashboard watches — the ADR-0023 smoke, first leg now
  real.
- **Seam reuse:** the SDK contract test reuses the existing `live_server(...)` uvicorn thread +
  testcontainers Postgres + greeter path; the SDK unit layer needs no server (fake transport), keeping
  the fast gate fast. The `sdk/chessroom` package gets its own ruff config mirroring the server's.

## Out of scope (pinned to the slice that proves it)
Non-Python SDKs (ADR-0021 defers) · a published-to-PyPI release + the literal standalone-repo split
(tracked follow-up under Q1/O-2, needs an owner PyPI account) · bot-management **browser** UI
(create-bot/see-key in the browser — V2 REST exists; still later polish, as in V6) · offering draws
from the SDK / an `on_your_turn` full-control hook (v1.x, Q2/Q3) · bundling a UCI engine binary
(user supplies) · increment time controls / 1+0 bullet (dormant, ADR-0025 #6) · a machine-readable
JSON-Schema derivation of PROTOCOL.md (ADR-0021 follow-up). **No server schema/behavior change.**

## Open items (to carry)
- **O-1 (reference bots = house bots):** the SDK's `RandomBot`/`MinimaxBot` **mirror** the server's
  in-process house bots but are **not shared-imported** (ADR-0021 decoupling forbids the server
  importing the SDK). The "double as house bots" intent (ADR-0022) is satisfied at the logic/
  documentation level, not by a code merge. Revisit only if we ever run house bots *as SDK WS
  clients* (they're in-process/sessionless today).
- **O-2 (Q1 extract-on-publish):** if Q1 lands as the monorepo package (★), the *literal* separate-repo
  + `pip install chessroom` from PyPI is a follow-up — a git-subtree/`filter-repo` split + a PyPI
  publish job (needs an owner PyPI account/token). Until then the quickstart installs by path/git.
- **O-3 (default URL):** the SDK defaults `CHESSROOM_URL` to the deployed `wss://engine-room.fly.dev`;
  local dev must override to `ws://localhost:8001`. Confirm the deployed WS path/host at impl (health
  check) — a wrong default silently sends newcomers' first bot to the wrong place.
- **O-4 (clock vs `choose_move` latency):** the SDK charges the bot's own thinking + network to its
  clock (PROTOCOL C8) — a slow `choose_move` can flag. The SDK should document this and optionally
  surface `state.clocks`; no move-time enforcement in the SDK itself (the server clock is the arbiter).
- **O-5 (UCI engine lifecycle):** `UCIBot` opens a `SimpleEngine` subprocess; it must be closed on
  exit/error (context manager / `run()` teardown) to avoid orphaned engine processes. Handle in the
  `run()` cleanup path.
- **O-6 (two wire clients remain):** after V7 the server still has `devtools/demo_bot.py` and
  `tests/support/fake_client.py`. Keep both — `fake_client` is the deterministic in-process test seam
  (drives timing edge cases the SDK abstracts away); `demo_bot` is the DB-aware dev launcher. The SDK
  does **not** replace them. Note the redundancy; don't collapse it in V7.
- **O-7 (SDK versioning/compat):** the SDK sends `protocol_version` in `hello`; PROTOCOL §2 has the
  server advertise a range and reject `VERSION_UNSUPPORTED`. The SDK should surface a clear error on
  version mismatch rather than a raw close. Wire a friendly message at impl.
```
