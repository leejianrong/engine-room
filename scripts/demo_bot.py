"""Demo bot — connect to a running Engine Room, start a match vs the house bot,
and print the spectator URL so you can watch it in the browser.

V1 has no lobby yet, so this is how you create a game to spectate. Run it against
the platform (e.g. after `docker compose --profile app up`):

    cd server && uv run python ../scripts/demo_bot.py            # one game
    cd server && uv run python ../scripts/demo_bot.py --loop     # keep starting games

Options: --api ws-host (default localhost:8001), --web (default localhost:5174),
--move-delay seconds (default 0.7), --startup-delay seconds (default 4),
--base/--inc time control, --token (default dev-token).
"""

import argparse
import asyncio
import json
import random

import chess
import websockets


async def play_one(args, rng: random.Random) -> None:
    async with websockets.connect(
        f"ws://{args.api}/api/bot/v1",
        additional_headers={"Authorization": f"Bearer {args.token}"},
    ) as ws:
        await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
        await ws.recv()  # welcome
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
        game_start = json.loads(await ws.recv())
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
            board = chess.Board(turn["fen"])
            uci = rng.choice(list(board.legal_moves)).uci()
            await ws.send(
                json.dumps({"type": "move", "game_id": game_id, "ply": turn["ply"], "uci": uci})
            )
            await asyncio.sleep(args.move_delay)
            while True:
                msg = json.loads(await ws.recv())
                if msg["type"] == "your_turn":
                    turn = msg
                    break
                if msg["type"] == "game_over":
                    print(f"Game over: {msg['result']} · {msg['termination']}\n", flush=True)
                    return


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="localhost:8001", help="backend host:port")
    p.add_argument("--web", default="localhost:5174", help="frontend host:port (for the URL)")
    p.add_argument("--token", default="dev-token")
    p.add_argument("--base", type=int, default=180)
    p.add_argument("--inc", type=int, default=0)
    p.add_argument("--move-delay", type=float, default=0.7, dest="move_delay")
    p.add_argument("--startup-delay", type=float, default=4.0, dest="startup_delay")
    p.add_argument("--loop", action="store_true", help="keep starting new games")
    args = p.parse_args()

    rng = random.Random()
    while True:
        await play_one(args, rng)
        if not args.loop:
            return


if __name__ == "__main__":
    asyncio.run(main())
