"""Demo bot — connect to a running Engine Room, start a match, and print the
spectator URL so you can watch it in the browser (dev only).

There's no lobby until V6, so this is how you create a game to spectate. It
authenticates with a real `crbk_` key (V2+); pass one with `--token`, or omit it
and one is minted for you (via `mint_bot`, needs DB access).

    cd server
    uv run python -m engine_room.devtools.demo_bot              # auto-mint, one game
    uv run python -m engine_room.devtools.demo_bot --loop       # keep starting games
    uv run python -m engine_room.devtools.demo_bot --token crbk_...   # use a specific key
    uv run python -m engine_room.devtools.demo_bot --engine random    # dumb (random) moves

By default the bot plays minimax + alpha-beta (`--engine`, `--depth 3`) so the
game looks like real chess. It pauses `--move-delay` (0.5s) before each move so
you can watch; pair it with ER_HOUSE_MOVE_DELAY_SECONDS so the house side is
paced too. Other options: --api (localhost:8001), --web (localhost:5174),
--startup-delay (4s), --base/--inc time control, --token.

(`websockets` is available in the server image via uvicorn[standard].)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random

import chess
import websockets

from ..game.minimax import choose_move as minimax_move


async def play_one(args, key: str, rng: random.Random) -> None:
    async with websockets.connect(
        f"ws://{args.api}/api/bot/v1",
        additional_headers={"Authorization": f"Bearer {key}"},
    ) as ws:
        await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
        welcome = json.loads(await ws.recv())
        if welcome.get("type") != "welcome":
            raise SystemExit(f"handshake failed: {welcome}")
        await ws.send(
            json.dumps(
                {
                    "type": "seek",
                    "id": "demo",
                    "time_control": {"base_seconds": args.base, "increment_seconds": args.inc},
                }
            )
        )
        await ws.recv()  # seek_ack
        # game_start is asynchronous since V3 (the matcher pairs us — with a real
        # opponent if one is queued, else the 3+0 greeter house bot).
        game_start = json.loads(await ws.recv())
        if game_start.get("type") != "game_start":
            raise SystemExit(f"expected game_start, got {game_start}")
        game_id = game_start["game_id"]
        turn = json.loads(await ws.recv())  # your_turn ply 0

        url = f"http://{args.web}/?game={game_id}"
        print("\n" + "=" * 60)
        print(f"  Match started vs {game_start['opponent']['name']}.")
        print(f"  Watch it here:  {url}")
        print(f"  (starting moves in {args.startup_delay}s — open the URL now)")
        print("=" * 60 + "\n", flush=True)
        await asyncio.sleep(args.startup_delay)

        while True:
            # Pause *before* moving so each side's move is spaced out for watching
            # (the pair to this is the server-side house move delay for Black).
            await asyncio.sleep(args.move_delay)
            board = chess.Board(turn["fen"])
            if args.engine == "minimax":
                uci = minimax_move(board, depth=args.depth, rng=rng)
            else:
                uci = rng.choice(list(board.legal_moves)).uci()
            await ws.send(
                json.dumps({"type": "move", "game_id": game_id, "ply": turn["ply"], "uci": uci})
            )
            while True:
                msg = json.loads(await ws.recv())
                if msg["type"] == "your_turn":
                    turn = msg
                    break
                if msg["type"] == "game_over":
                    print(f"Game over: {msg['result']} · {msg['termination']}\n", flush=True)
                    return


async def _resolve_key(args) -> str:
    if args.token:
        return args.token
    from .mint_bot import mint_key  # local import: only needed for auto-mint

    _, key = await mint_key()
    print("demo-bot: no --token given; minted a local dev key.", flush=True)
    return key


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="localhost:8001", help="backend host:port")
    p.add_argument("--web", default="localhost:5174", help="frontend host:port (for the URL)")
    p.add_argument("--token", default=None, help="crbk_ API key; auto-minted if omitted")
    p.add_argument("--base", type=int, default=180)
    p.add_argument("--inc", type=int, default=0)
    p.add_argument("--move-delay", type=float, default=0.5, dest="move_delay",
                   help="pause before each move (watchability); charged to the bot's clock")
    p.add_argument("--startup-delay", type=float, default=4.0, dest="startup_delay")
    p.add_argument("--engine", choices=["minimax", "random"], default="minimax",
                   help="move engine (default: minimax + alpha-beta)")
    p.add_argument("--depth", type=int, default=3, help="minimax search depth")
    p.add_argument("--loop", action="store_true", help="keep starting new games")
    args = p.parse_args()

    key = await _resolve_key(args)
    rng = random.Random()
    while True:
        await play_one(args, key, rng)
        if not args.loop:
            return


if __name__ == "__main__":
    asyncio.run(main())
