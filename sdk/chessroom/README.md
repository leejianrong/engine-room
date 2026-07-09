# chessroom — Python SDK for Engine Room

Write an AI chess bot in a few lines and play it live on
[Engine Room](https://engine-room.fly.dev). You implement one method —
`choose_move(board)` — and the SDK handles everything else: the authenticated
WebSocket, matchmaking, reconnects, heartbeats, and the whole wire protocol.

```python
from chessroom import Bot
import random

class MyBot(Bot):
    def choose_move(self, board):        # board is a python-chess Board
        return random.choice(list(board.legal_moves))

MyBot().run(loop=True)                    # reads CHESSROOM_KEY / CHESSROOM_URL
```

## Install

```bash
uv add chessroom          # or: pip install chessroom
```

> During V7 the package lives in the Engine Room monorepo (`sdk/chessroom`); the
> quickstart installs it by path/git until it's published to PyPI (V7 O-2).

## Configure

- `CHESSROOM_KEY` (**required**) — your per-bot API key (`crbk_…`), created in the
  dashboard and shown once. Locally, `make mint` prints one.
- `CHESSROOM_URL` (optional) — the WebSocket endpoint. Defaults to the live
  platform (`wss://engine-room.fly.dev/api/bot/v1`); for local dev use
  `ws://localhost:8001/api/bot/v1`.

Both can also be passed explicitly: `Bot(key=..., url=..., time_control=(180, 0))`.

## What the SDK hides

Per [PROTOCOL.md](https://github.com/leejianrong/engine-room/blob/main/docs/design/PROTOCOL.md):
the `hello`/`welcome` handshake, auto-`seek`, the `your_turn`→`move`→`move_ack`
loop, **heartbeat pong** (§10), **`ply`-idempotent resends** on a lost ack (§9),
and **reconnect-resume** from `welcome.active_game` after a dropped socket (§8).
You never see a disconnect.

## Beyond `choose_move`

- Return `chessroom.RESIGN` from `choose_move` to resign; when
  `state.opponent_draw_offer` is set, return `chessroom.ACCEPT_DRAW` to agree a
  draw (a normal move declines it).
- Override `on_game_start(info)` / `on_game_over(result)` for optional callbacks.

## Reference bots

- `chessroom.RandomBot` — the hello-world (uniformly random legal move).
- `chessroom.MinimaxBot` — a depth-limited minimax + alpha-beta example.

## UCI bridge

Point an existing UCI engine (e.g. Stockfish) at the platform — client-side, no
server changes:

```bash
CHESSROOM_KEY=crbk_... chessroom-uci --engine /usr/bin/stockfish --think-time 0.1
```
