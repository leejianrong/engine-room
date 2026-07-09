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
    uv run python -m engine_room.devtools.demo_bot --drop-after 4      # V4 reconnect demo

By default the bot plays minimax + alpha-beta (`--engine`, `--depth 3`) so the
game looks like real chess. It pauses `--move-delay` (0.5s) before each move so
you can watch; pair it with ER_HOUSE_MOVE_DELAY_SECONDS so the house side is
paced too.

V4 (resilience): the bot answers heartbeat `ping` frames with `pong`, and if the
socket drops mid-game it reconnects with the same key and **resumes the same
game** from `welcome.active_game` (PROTOCOL §8). `--drop-after N` deliberately
kills and reopens the socket after N of the bot's own moves so you can watch it
reconnect and finish the game — the V4 demo.

Other options: --api (localhost:8001), --web (localhost:5174),
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


async def _connect(args, key: str):
    """Open a socket and complete the hello handshake; return (ws, welcome)."""
    ws = await websockets.connect(
        f"ws://{args.api}/api/bot/v1",
        additional_headers={"Authorization": f"Bearer {key}"},
    )
    await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
    welcome = json.loads(await ws.recv())
    if welcome.get("type") != "welcome":
        raise SystemExit(f"handshake failed: {welcome}")
    return ws, welcome


async def _next(ws) -> dict:
    """Read the next protocol frame, transparently answering heartbeat pings
    (§10) so a paced/long game is never closed for missed liveness."""
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("type") == "ping":
            await ws.send(json.dumps({"type": "pong", "t": msg.get("t", 0)}))
            continue
        return msg


async def _next_turn(ws) -> dict:
    """Read until the next actionable frame — your_turn or game_over — skipping
    move_ack (and pings)."""
    while True:
        msg = await _next(ws)
        if msg["type"] in ("your_turn", "game_over"):
            return msg


def _pick_move(turn: dict, args, rng: random.Random) -> str:
    board = chess.Board(turn["fen"])
    if args.engine == "minimax":
        return minimax_move(board, depth=args.depth, rng=rng)
    return rng.choice(list(board.legal_moves)).uci()


async def _reconnect_resume(args, key: str, game_id: str):
    """Reopen the socket and resume the live game from welcome.active_game (§8).
    Returns (ws, turn) where `turn` is the your_turn/game_over to act on, or
    (ws, None) if there is nothing to resume."""
    ws, welcome = await _connect(args, key)
    active = welcome.get("active_game")
    if active and active.get("game_id") == game_id:
        print(f"  ↻ reconnected — resumed {game_id} at ply {active['ply']}", flush=True)
        # If it's our move the server re-sends your_turn; otherwise we wait for it.
        return ws, await _next_turn(ws)
    # No active game: the server may have queued the missed game_over (D-vi).
    return ws, None


async def play_one(args, key: str, rng: random.Random) -> None:
    ws, _ = await _connect(args, key)
    await ws.send(
        json.dumps(
            {
                "type": "seek",
                "id": "demo",
                "time_control": {"base_seconds": args.base, "increment_seconds": args.inc},
            }
        )
    )
    # game_start is asynchronous since V3 (the matcher pairs us — with a real
    # opponent if one is queued, else the 3+0 greeter house bot). Skip the
    # seek_ack and any stale game_over left over from a previous game (D-vi
    # delivers a missed result on the next connect).
    while True:
        msg = await _next(ws)
        if msg.get("type") == "game_start":
            game_start = msg
            break
    game_id = game_start["game_id"]

    url = f"http://{args.web}/?game={game_id}"
    print("\n" + "=" * 60)
    print(f"  Match started vs {game_start['opponent']['name']}.")
    print(f"  Watch it here:  {url}")
    print(f"  (starting moves in {args.startup_delay}s — open the URL now)")
    print("=" * 60 + "\n", flush=True)
    await asyncio.sleep(args.startup_delay)

    turn = await _next_turn(ws)  # your_turn ply 0
    my_moves = 0
    while True:
        if turn["type"] == "game_over":
            print(f"Game over: {turn['result']} · {turn['termination']}\n", flush=True)
            await ws.close()
            return

        await asyncio.sleep(args.move_delay)
        uci = _pick_move(turn, args, rng)
        try:
            await ws.send(
                json.dumps({"type": "move", "game_id": game_id, "ply": turn["ply"], "uci": uci})
            )
            turn = await _next_turn(ws)
        except websockets.ConnectionClosed:
            ws, turn = await _reconnect_resume(args, key, game_id)
            if turn is None:
                print("  (game already ended while reconnecting)\n", flush=True)
                await ws.close()
                return
            continue

        my_moves += 1
        # V4 demo: deliberately drop mid-game, then reconnect and resume.
        if args.drop_after and my_moves == args.drop_after:
            print(f"  ✂ simulating a mid-game disconnect after {my_moves} moves…", flush=True)
            await ws.close()
            await asyncio.sleep(args.drop_pause)
            ws, turn = await _reconnect_resume(args, key, game_id)
            if turn is None:
                await ws.close()
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
    p.add_argument("--drop-after", type=int, default=0, dest="drop_after",
                   help="V4 demo: kill+reconnect the socket after N of the bot's moves (0=never)")
    p.add_argument("--drop-pause", type=float, default=1.0, dest="drop_pause",
                   help="seconds to stay disconnected in the --drop-after demo")
    args = p.parse_args()

    key = await _resolve_key(args)
    rng = random.Random()
    while True:
        await play_one(args, key, rng)
        if not args.loop:
            return


if __name__ == "__main__":
    asyncio.run(main())
