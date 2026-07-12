# API reference

The whole SDK is one class you subclass and one method you override. This page is
the contract for everything you can touch.

## `Bot`

```python
from engineroom import Bot

class Bot:
    def __init__(self, key=None, url=None, *,
                 time_control=(180, 0), connect=None): ...
```

Subclass `Bot`, implement `choose_move`, call `run()`.

| Argument | Default | Meaning |
|----------|---------|---------|
| `key` | `None` → `ENGINEROOM_KEY` | Your bot's API key (`crbk_…`). Falls back to the env var, then errors if neither is set. |
| `url` | `None` → `ENGINEROOM_URL` → live | WebSocket endpoint. Falls back to the env var, then to the live platform. |
| `time_control` | `(180, 0)` | `(base_seconds, increment_seconds)`. `(180, 0)` is 3+0; `(300, 0)` is 5+0. This picks the matchmaking pool. |
| `connect` | `None` | An async factory returning a transport. For tests — leave it unset to use a real WebSocket. |

A bot's display name isn't set here. It comes from the API key, which is tied to
the bot you created in the dashboard.

## `choose_move(board)`

```python
def choose_move(self, board: chess.Board) -> Move | str | object:
    ...
```

The one method you must implement. It's called every time it's your move, with a
[`python-chess`](https://python-chess.readthedocs.io/) `Board` at the current
position. Return one of:

| Return value | Effect |
|--------------|--------|
| a `chess.Move` | play that move |
| a UCI string, e.g. `"e2e4"`, `"e7e8q"` | play that move |
| `engineroom.RESIGN` | resign; the opponent wins |
| `engineroom.ACCEPT_DRAW` | agree a standing draw offer |

The board is rebuilt from the server's FEN each turn, so it always reflects the
true position — you never sync a board yourself. Read `board.legal_moves`,
`board.turn`, `board.piece_map()`, push and pop candidate moves; it's an ordinary
`chess.Board`.

### Per-turn state on `self`

Just before each `choose_move` call the SDK sets two read-only attributes on the
bot, so you react to them without changing the method signature:

| Attribute | Type | Meaning |
|-----------|------|---------|
| `self.opponent_draw_offer` | `bool` | `True` when the opponent has a standing draw offer this turn. Return `engineroom.ACCEPT_DRAW` to agree; a normal move declines it. |
| `self.turn_state` | `TurnState` or `None` | The full parsed `your_turn` frame — `game_id`, `ply`, `fen`, `last_move`, `clocks`, `your_color`, `opponent_draw_offer` — for advanced use. `None` before the first turn. |

A draw offer is **not** encoded in the FEN, so the board alone can't tell you one
is pending — check `self.opponent_draw_offer`:

```python
class PeaceLover(Bot):
    def choose_move(self, board):
        if self.opponent_draw_offer:
            return ACCEPT_DRAW
        return random.choice(list(board.legal_moves))
```

!!! warning "Return a legal move, or forfeit"
    An illegal or unparseable move on your turn ends the game immediately — an
    instant forfeit. When in doubt, pick from `board.legal_moves`. The clock is also
    live while you think, so don't block for seconds.

### The control sentinels

```python
from engineroom import RESIGN, ACCEPT_DRAW
```

`RESIGN` and `ACCEPT_DRAW` are unique marker objects, not strings — return the
object itself. `RESIGN` gives up the game at once. `ACCEPT_DRAW` accepts a draw the
opponent has offered — check `self.opponent_draw_offer` (above) to know when one is
pending; if there's no standing offer it's a harmless no-op. Playing a normal move
declines any offer on the table.

Draws for the standard reasons — stalemate, insufficient material, threefold
repetition, the fifty-move rule — are applied by the server automatically. You
never claim them. `ACCEPT_DRAW` is only for a draw the opponent proposes.

## `run(loop=False)`

```python
def run(self, *, loop: bool = False) -> None:
```

Connects and plays. Blocking — it owns the event loop (`asyncio.run` underneath),
so call it once from your `__main__`.

- `run()` plays one game and returns.
- `run(loop=True)` seeks a new game after each one finishes and never returns. This
  is what you want for a bot that lives in the pools.

## Optional hooks

Override either to observe the game. Neither is required, and neither affects play.

```python
def on_game_start(self, info: GameStart) -> None: ...
def on_game_over(self, result: GameOver) -> None: ...
```

`on_game_start` fires once when a game is paired; `on_game_over` fires once when it
ends. Use them to log, track a score, or print the result.

```python
class ChattyBot(RandomBot):
    def on_game_start(self, info):
        print(f"playing {info.your_color} vs {info.opponent.get('name')}")

    def on_game_over(self, result):
        print(f"{result.result} by {result.termination}")
        if result.rating:
            print(f"rating {result.rating['before']} → {result.rating['after']}")
```

### `GameStart`

Passed to `on_game_start`. A frozen dataclass:

| Field | Type | Notes |
|-------|------|-------|
| `game_id` | `str` | |
| `your_color` | `str` | `"white"` or `"black"` |
| `opponent` | `dict` | `{id, name, rating}` |
| `time_control` | `dict` | `{base_seconds, increment_seconds}` |
| `initial_fen` | `str` | starting position |
| `clocks` | `dict` | `{white_ms, black_ms}` |
| `start_grace_ms` | `int` | grace before the first clock starts |

On a mid-game reconnect the SDK synthesizes a partial `GameStart` from the resume
payload — `opponent`, `time_control`, and `start_grace_ms` come through empty.

### `GameOver`

Passed to `on_game_over`. A frozen dataclass:

| Field | Type | Notes |
|-------|------|-------|
| `game_id` | `str` | |
| `result` | `str` | `white_wins` · `black_wins` · `draw` · `aborted` |
| `termination` | `str` | `checkmate`, `timeout`, `resignation`, `stalemate`, `agreement`, … |
| `final_fen` | `str` | |
| `pgn` | `str` | the full game |
| `rating` | `dict` or `None` | `{before, after}` — this bot's Elo change; `None` for an aborted (unrated) game |

## Configuration

Config resolves from constructor arguments first, then the environment.

| Variable | Purpose | Default |
|----------|---------|---------|
| `ENGINEROOM_KEY` | your bot's API key (**required**) | — |
| `ENGINEROOM_URL` | WebSocket endpoint | `wss://engine-room.fly.dev/api/bot/v1` |

For local development against `make dev`, set
`ENGINEROOM_URL=ws://localhost:8001/api/bot/v1`.

!!! note "Legacy variable names"
    The older `CHESSROOM_KEY` / `CHESSROOM_URL` names still work as a fallback, but
    they're deprecated — reading a value from one prints a one-time
    `DeprecationWarning`. Migrate to `ENGINEROOM_*`.

## Reference bots

Three complete bots ship with the SDK — the rungs of the
[tutorial ladder](tutorial.md). Each is a `Bot` you can run as-is.

```python
from engineroom import RandomBot, GreedyBot, MinimaxBot

RandomBot().run(loop=True)                 # any legal move
GreedyBot().run(loop=True)                 # one-ply material
MinimaxBot(depth=3).run(loop=True)         # search + alpha-beta
```

`RandomBot` and `GreedyBot` take an optional `seed` for reproducible play;
`MinimaxBot` takes `depth` (default `3`) and `seed`. They accept the same `key` /
`url` / `time_control` arguments as any `Bot`.

For pointing an existing UCI engine at the platform, see the
[UCI bridge](uci.md) and `engineroom.UCIBot`.

## Errors

All SDK errors subclass `engineroom.ChessroomError`:

| Exception | Raised when |
|-----------|-------------|
| `ConfigError` | no API key is set |
| `ProtocolError` | the server sent a fatal or unexpected frame (bad key, unsupported protocol version) |

A dropped connection is *not* an error — the SDK reconnects and resumes on its own.
