# UCI bridge

Already have a chess engine? Point it at Engine Room without rewriting a thing. The
`engineroom-uci` bridge runs any [UCI](https://en.wikipedia.org/wiki/Universal_Chess_Interface)
engine — Stockfish, Leela, your own — as a local subprocess and relays its moves.

```bash
engineroom-uci --engine /usr/bin/stockfish --think-time 0.1
```

The engine runs entirely on your machine. The bridge asks it for a move and forwards
that move over the wire. Nothing about your engine changes, and the server never
runs native code — it only ever sees the moves.

```mermaid
flowchart LR
    E["Stockfish<br/>(UCI subprocess)"]
    B["engineroom-uci<br/>(the bridge)"]
    S["Engine Room"]
    E <-->|"UCI · stdin/stdout"| B
    B <-->|"WebSocket · moves"| S

    classDef engine fill:#fff3e0,stroke:#fb8c00,color:#e65100;
    classDef bridge fill:#e8eaf6,stroke:#3949ab,color:#1a237e;
    classDef server fill:#f1f8e9,stroke:#7cb342,color:#33691e;
    class E engine;
    class B bridge;
    class S server;
```

`engineroom-uci` is installed with the SDK (`pip install engineroom`). The engine
binary is not — supply your own. Stockfish is a package away on most systems
(`brew install stockfish`, `apt install stockfish`).

## Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--engine` | *required* | path to the UCI engine binary |
| `--think-time` | `0.1` | seconds the engine may think per move |
| `--depth` | — | fixed search depth (overrides `--think-time`) |
| `--key` | `ENGINEROOM_KEY` | API key, if not from the env |
| `--url` | `ENGINEROOM_URL` | WebSocket endpoint, if not from the env |
| `--base` | `180` | clock base in seconds (`180` = 3+0) |
| `--inc` | `0` | clock increment in seconds |
| `--loop` | off | keep seeking new games after each finishes |

Set your key in the environment and the command stays short:

```bash
export ENGINEROOM_KEY=crbk_your_key
engineroom-uci --engine /usr/bin/stockfish --think-time 0.2 --loop
```

!!! tip "Match think time to the clock"
    `--think-time` is a per-move budget for the engine, not the game clock. On a 3+0
    game a fixed `0.1`–`0.3` seconds a move keeps a full game well inside three
    minutes while still playing strongly. Prefer `--depth` when you want repeatable
    strength regardless of the machine.

## In code

`engineroom.UCIBot` is a `Bot` whose `choose_move` delegates to the engine
subprocess, so you can embed it or subclass it like any other bot:

```python
from engineroom import UCIBot

bot = UCIBot("/usr/bin/stockfish", think_time=0.1, time_control=(180, 0))
bot.run(loop=True)      # shuts the engine subprocess down cleanly on exit
```

Pass `depth=` instead of `think_time=` to search to a fixed depth. The engine
process is launched on the first move and closed when `run` returns, so you won't
leave an orphaned Stockfish behind.

!!! warning "The bridge is a real opponent"
    A strong engine on a fast think time will outrate everything in the pools in
    short order. That's fine — but if you're benchmarking your *own* bot against the
    house opponents, keep the engine bots separate so the ratings stay meaningful.
