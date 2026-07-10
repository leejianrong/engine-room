# engineroom — Python SDK for Engine Room

Write an AI chess bot in a few lines and play it live on
[Engine Room](https://engine-room.fly.dev). You implement one method —
`choose_move(board)` — and the SDK handles everything else: the authenticated
WebSocket, matchmaking, reconnects, heartbeats, and the whole wire protocol.

```python
from engineroom import Bot
import random

class MyBot(Bot):
    def choose_move(self, board):        # board is a python-chess Board
        return random.choice(list(board.legal_moves))

MyBot().run(loop=True)                    # reads CHESSROOM_KEY / CHESSROOM_URL
```

## Install

```bash
pip install engineroom     # or: uv add engineroom
```

> The package is developed in the Engine Room monorepo (`sdk/engineroom`) and
> published to PyPI from there via the `publish-sdk` GitHub workflow (see
> [Publishing / Releasing](#publishing--releasing)).

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

- Return `engineroom.RESIGN` from `choose_move` to resign; when
  `state.opponent_draw_offer` is set, return `engineroom.ACCEPT_DRAW` to agree a
  draw (a normal move declines it).
- Override `on_game_start(info)` / `on_game_over(result)` for optional callbacks.

## Reference bots

- `engineroom.RandomBot` — the hello-world (uniformly random legal move).
- `engineroom.MinimaxBot` — a depth-limited minimax + alpha-beta example.

## UCI bridge

Point an existing UCI engine (e.g. Stockfish) at the platform — client-side, no
server changes:

```bash
CHESSROOM_KEY=crbk_... engineroom-uci --engine /usr/bin/stockfish --think-time 0.1
```

## Publishing / Releasing

The SDK is published to [PyPI](https://pypi.org/project/engineroom/) by the
`.github/workflows/publish-sdk.yml` workflow using **trusted publishing** (OIDC):
no API token is ever stored in the repo. The workflow builds the sdist + wheel
from `sdk/engineroom/` with `uv build` and uploads them with
`pypa/gh-action-pypi-publish` from the `pypi` GitHub Environment.

### One-time human setup (before the first release)

1. **Create the PyPI project + Trusted Publisher.** On
   [pypi.org](https://pypi.org) → *Your projects* → *Publishing* → add a new
   **pending publisher** for a project named `engineroom` with:
   - **Owner / repository:** `leejianrong/engine-room`
   - **Workflow name:** `publish-sdk.yml`
   - **Environment:** `pypi`

   (A pending publisher lets the very first upload create the project; no manual
   first upload or token is needed.)
2. **Create the GitHub Environment** named `pypi` (repo *Settings → Environments*).
   Optionally add required reviewers so a human approves each publish.

### Cutting a release

1. Bump the version in **both** `pyproject.toml` (`[project].version`) and
   `src/engineroom/const.py` (`SDK_VERSION`) — keep them in lockstep — and merge to `main`.
2. Publish a **GitHub Release** whose tag matches `engineroom-v*`
   (e.g. `engineroom-v0.1.0`). That triggers the workflow, which builds and
   publishes to PyPI. (`workflow_dispatch` can also run it manually.)
