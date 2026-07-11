# Engine Room quickstart — your first bot in minutes

Zero to a live, watchable chess game. You write ~3 lines; the `engineroom` SDK does
the rest (ADR-0022, target < 20 min).

## Steps

1. **Get a key.** Sign in to the [dashboard](https://engine-room.fly.dev), create a
   bot, and copy its API key (`crbk_…`) — it's shown once.
   *(Local dev: run `make mint` in the repo root to print a key.)*

2. **Clone + configure.**
   ```bash
   git clone <this-quickstart>
   cd quickstart
   cp .env.example .env          # paste your ENGINEROOM_KEY into .env
   ```

3. **Install + run** (needs [`uv`](https://docs.astral.sh/uv/), ADR-0024):
   ```bash
   uv sync
   uv run python random_bot.py
   ```

4. **Watch.** Open the dashboard — your bot is matched and playing. 🎉

## Make it smarter

Everything interesting is one method in `random_bot.py`:

```python
class RandomBot(Bot):
    def choose_move(self, board):        # board: a python-chess Board
        return random.choice(list(board.legal_moves))
```

Return any legal move (a `chess.Move` or a UCI string). Try material-counting,
then search. When you're ready, the SDK also ships `engineroom.MinimaxBot` and a
`engineroom-uci` bridge to point an engine like Stockfish at the platform.

## Local dev

Running the platform yourself (`make dev`)? Uncomment `ENGINEROOM_URL` in `.env` to
point at `ws://localhost:8001/api/bot/v1`.

## Docker (optional / advanced)

The hero path is `uv`, no container (ADR-0024). A `Dockerfile` is included for the
containerized path — see its header for the one caveat while the SDK is
path-installed (pre-PyPI).
