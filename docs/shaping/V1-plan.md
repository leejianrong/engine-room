---
shaping: true
---

# V1 Plan — Skeleton thread

Implementation plan for slice **V1** (from Shape A, part A1). Higher levels: [slices.md](slices.md) (slice def), [shaping.md](shaping.md) (R's, Shape A, A1 breadboard U1–U2/N1–N10). This doc is ground truth for V1 implementation detail.

## Goal (definition of done)
Run the server + a stub bot-client. It connects, seeks 3+0, is paired with the in-process house `RandomBot`, and plays a full legal `python-chess` game to a natural terminal or a **timeout**. A SvelteKit page shows moves appear live via SSE. On game end, one `games` row exists in Postgres with result, termination, final FEN, and full PGN. The whole thread is exercised by the fake-protocol-client test seam.

## Build-time decisions (pinned for V1)
| # | Decision | Rationale |
|---|----------|-----------|
| D-a | **Persistence:** SQLAlchemy 2.0 async ORM + Alembic; `asyncpg` driver | User-selected; typed models reused by V2 REST/V3 matchmaking; migrations manage V2/V5 schema growth |
| D-b | **Frontend:** real SvelteKit + Vite project stood up now; V1 builds the bare live view in it | User-selected; V6 extends rather than replaces |
| D-c | **Server tooling:** `uv` + `pyproject.toml` | Consistency with bot tooling (ADR-0024); one toolchain |
| D-d | **Concurrency:** one asyncio task per active game; in-memory `GameRegistry`; single process | ADR-0020 single-process MVP; game state in-memory (ADR-0018) |
| D-e | **Clock source:** `loop.time()` monotonic; per-seat remaining ms; enforced via `asyncio.wait_for(recv_move, remaining)` | PROTOCOL §6 send-instant semantics; monotonic source is impl detail per PROTOCOL note |
| D-f | **House bot as an in-process seat**, not a WebSocket client — implements the same `Seat.get_move()` contract the game loop calls | Avoids a loopback socket; keeps the loop transport-agnostic (helps A4/scale later) |
| D-g | **Auth:** single fixed dev token checked at handshake (stub) | Real OAuth+hashed keys is V2; keeps V1 thin (R5) |
| D-h | **Time control:** 3+0 hardcoded | 5+0 pool + selection is V3; V1 proves the clock |

## Project layout (established this slice)
```
engine-room/
  server/                    # uv project (pyproject.toml)
    engine_room/
      app.py                 # FastAPI app factory, routes mounted
      config.py              # settings (DSN, dev token)
      protocol/              # wire (de)serialization — mirrors PROTOCOL.md
        messages.py          # typed message models (pydantic)
      ws/
        bot_endpoint.py      # N1/N2 handshake + seek over /api/bot/v1
        session.py           # per-connection Session (ws + send queue)
      matchmaking/
        queue.py             # MatchmakingQueue interface
        always_pair.py       # N3 trivial impl (behind the interface)
      game/
        registry.py          # GameRegistry (in-memory)
        worker.py            # N5 game loop (asyncio task per game)
        clock.py             # N6 server clock
        seat.py              # Seat contract; WsSeat + HouseSeat
        house_bots.py        # N4 RandomBot
      pubsub/
        base.py              # PubSub interface
        inproc.py            # N7 in-process impl
      spectate/
        sse.py               # N9 SSE endpoint
      persistence/
        models.py            # SQLAlchemy models (Game)
        finalize.py          # N8 atomic finalization
        db.py                # async engine/session
    alembic/                 # migrations (0001_games)
    tests/
      fake_client.py         # fake protocol client (WS test seam)
      test_v1_happy_path.py
      test_v1_clock_flag.py
      test_v1_finalization.py
  frontend/                  # SvelteKit + Vite (D-b)
    src/routes/+page.svelte  # U1/U2 bare live view (EventSource → move list)
  docker-compose.yml         # local Postgres
```
(The `chessroom` SDK is a **separate repo** per ADR-0021 — not created here; V1's client is `tests/fake_client.py`.)

## Affordance → module map
| Affordance | Module | Notes |
|-----------|--------|-------|
| N1 handshake (stub-auth) | `ws/bot_endpoint.py` | check dev token header; `hello`→`welcome` |
| N2 seek handler | `ws/bot_endpoint.py` | `seek{3+0}`→`seek_ack`; enqueue to N3 |
| N3 always-pair matcher | `matchmaking/always_pair.py` | behind `MatchmakingQueue`; pair with HouseSeat → create Game PAIRED → `game_start` |
| N4 house `RandomBot` | `game/house_bots.py` | `random.choice(list(board.legal_moves))` |
| N5 game loop + board | `game/worker.py` | asyncio task; `your_turn`/`move`/`move_ack`; terminal via `python-chess` |
| N6 server clock | `game/clock.py` | per-seat ms; `wait_for(recv, remaining)`; flag→timeout |
| N7 pubsub | `pubsub/inproc.py` | publish move/game_over to per-game channel |
| N8 finalizer | `persistence/finalize.py` | single txn write of Game record |
| N9 SSE | `spectate/sse.py` | subscribe N7 channel; `text/event-stream` |
| N10 Postgres | `persistence/models.py` + Alembic | `games` table |
| U1/U2 view | `frontend/src/routes/+page.svelte` | `EventSource('/api/spectate/'+gameId)` |

## Data model (V1 minimal — Alembic `0001_games`)
Forward-compatible: V2 adds `white_bot_id`/`black_bot_id` FKs; V5 adds rating deltas.
```python
class Game(Base):
    __tablename__ = "games"
    id: Mapped[str] = mapped_column(primary_key=True)          # "game_..." 
    result: Mapped[str]            # white_wins|black_wins|draw|aborted
    termination: Mapped[str]       # checkmate|timeout|stalemate|... (ADR-0008 vocab)
    final_fen: Mapped[str]
    pgn: Mapped[str]               # python-chess rendered
    base_seconds: Mapped[int]      # 180
    increment_seconds: Mapped[int] # 0
    white_name: Mapped[str]        # V1: stub/house names; V2 → FK
    black_name: Mapped[str]
    created_at: Mapped[datetime]
    finished_at: Mapped[datetime]
```

## Key contracts
```python
# game/seat.py  — the loop is transport-agnostic (D-f)
class Seat(Protocol):
    color: chess.Color
    async def send(self, msg: dict) -> None: ...        # your_turn, game_over
    async def get_move(self, deadline_ms: int) -> str:  # returns UCI; raises Flag on timeout
        ...
# WsSeat wraps a Session; HouseSeat wraps a house bot fn.

# matchmaking/queue.py  (R6 — real impl swaps in at V3)
class MatchmakingQueue(Protocol):
    async def seek(self, session, time_control) -> None: ...

# pubsub/base.py  (R6 — Redis impl swaps in at scale-out)
class PubSub(Protocol):
    async def publish(self, channel: str, event: dict) -> None: ...
    def subscribe(self, channel: str) -> AsyncIterator[dict]: ...
```

## Game loop sketch (N5 + N6)
```
game_start → both seats notified; White is side-to-move
loop:
    t_send = loop.time()
    await mover_seat.send(your_turn{ply, fen, last_move, clocks})
    try:
        uci = await mover_seat.get_move(deadline_ms = remaining[mover])
    except Flag:
        result = other side wins, termination="timeout"; break
    elapsed_ms = (loop.time() - t_send)*1000
    remaining[mover] -= elapsed_ms          # increment credited post-move (0 at MVP)
    if not board.is_legal(uci): ...          # V1: house is always legal; full forfeit path is V4
    board.push_uci(uci); ply += 1
    await mover_seat.send(move_ack)
    await pubsub.publish(chan, {move, fen, clocks})
    if board.is_game_over(): result/termination from python-chess; break
    swap mover
finalize(result, termination, board) → one txn; publish game_over
```

## Build sub-steps (order within V1)
1. **Scaffold** — `uv` project, FastAPI app factory, `config`, `docker-compose` Postgres, async engine, Alembic + `0001_games`, SvelteKit project. *Checkpoint: app boots, migration applies.*
2. **Handshake + seek (N1/N2)** — `/api/bot/v1`, stub-auth, `hello`/`welcome`/`seek`/`seek_ack`. *Checkpoint: fake client completes handshake + seek.*
3. **Pair + house bot (N3/N4)** — always-pair matcher behind interface, HouseSeat/RandomBot, `game_start`. *Checkpoint: fake client receives `game_start` vs house.*
4. **Game loop + clock (N5/N6)** — `your_turn`/`move`/`move_ack`, python-chess apply/terminal, clock + flag. *Checkpoint: a full game completes to a terminal in memory.*
5. **PubSub + SSE (N7/N9)** — in-proc bus, SSE endpoint. *Checkpoint: curl the SSE stream, see move events.*
6. **Finalize (N8/N10)** — atomic Game write. *Checkpoint: `games` row after a game.*
7. **SvelteKit view (U1/U2)** — `+page.svelte` EventSource move list + status. *Checkpoint: browser shows live moves — the V1 demo.*
8. **Tests** — see below. *Checkpoint: WS-seam suite green.*

## Tests (primary WS seam — PRD Option A)
`tests/fake_client.py`: a `FakeBot` over Starlette `TestClient.websocket_connect` with `hello()/seek()/expect(type)/move(uci)` helpers; SSE asserted via `TestClient` streaming GET.
- `test_v1_happy_path` — connect→seek→`game_start`→`your_turn`/`move` loop vs house→`game_over` with a real result and non-empty PGN.
- `test_v1_clock_flag` — a `FakeBot` that never answers `your_turn` flags; `game_over.termination=="timeout"`, opponent wins.
- `test_v1_finalization` — after a game, exactly one `games` row with matching result/termination/final_fen/pgn.
- (legality of house moves is implicitly covered — RandomBot only emits legal UCI; malformed-frame *forfeit* semantics are deferred to V4, asserted there.)

## Out of scope (pinned to the slice that proves it)
Auth→V2 · Elo/pools/TTL/same-owner→V3 · reconnect/`ply`-idempotency/heartbeat/illegal-forfeit→V4 · resign/draw/auto-draw/real-Elo→V5 · catch-up-snapshot/replay/lobby/styling→V6 · packaged SDK/quickstart/UCI-bridge→V7 · 5+0→V3.

## Open items (do not block V1)
- **K3/K4** (hosting/concurrency) — V1 is a single local process; deployment undecided.
- Exact clock start instant (send vs socket-flush) — V1 uses send-instant (`loop.time()` at `your_turn` send); revisit only if latency tests demand it.
- `games` column set may gain `id` scheme/index tweaks in V2 when FKs land — Alembic handles it.
