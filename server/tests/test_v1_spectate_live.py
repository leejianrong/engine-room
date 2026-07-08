"""V1 sub-step 5 checkpoint (end-to-end): SSE shows move events during a live game.

Runs a real uvicorn server, connects a real bot over WebSocket (drives moves),
and reads the spectator SSE stream over real HTTP — the automated equivalent of
`curl`-ing the stream while a game is in progress.
"""

import asyncio
import contextlib
import json
import random
import threading

import chess
import httpx
import uvicorn
import websockets

from engine_room.app import create_app


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # don't touch signals off the main thread
        pass


@contextlib.asynccontextmanager
async def live_server():
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_level="warning")
    server = _Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def test_sse_streams_a_live_game():
    async with live_server() as hostport:
        async with websockets.connect(
            f"ws://{hostport}/api/bot/v1",
            additional_headers={"Authorization": "Bearer dev-token"},
        ) as ws:
            await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
            await ws.recv()  # welcome
            await ws.send(
                json.dumps(
                    {"type": "seek", "id": "c1", "time_control": {"base_seconds": 180, "increment_seconds": 0}}
                )
            )
            await ws.recv()  # seek_ack
            game_start = json.loads(await ws.recv())
            game_id = game_start["game_id"]
            first_turn = json.loads(await ws.recv())  # your_turn ply 0 — bot paused here

            async with httpx.AsyncClient(base_url=f"http://{hostport}") as client:
                async with client.stream("GET", f"/api/spectate/{game_id}") as resp:
                    assert resp.status_code == 200
                    assert resp.headers["content-type"].startswith("text/event-stream")

                    async def drive_bot(turn: dict) -> None:
                        rng = random.Random(7)
                        while True:
                            board = chess.Board(turn["fen"])
                            uci = rng.choice(list(board.legal_moves)).uci()
                            await ws.send(
                                json.dumps(
                                    {"type": "move", "game_id": game_id, "ply": turn["ply"], "uci": uci}
                                )
                            )
                            while True:
                                msg = json.loads(await ws.recv())
                                if msg["type"] == "your_turn":
                                    turn = msg
                                    break
                                if msg["type"] == "game_over":
                                    return

                    async def read_sse() -> list[dict]:
                        events = []
                        async for line in resp.aiter_lines():
                            if line.startswith("data:"):
                                ev = json.loads(line[len("data:"):].strip())
                                events.append(ev)
                                if ev["type"] == "game_over":
                                    return events
                        return events

                    driver = asyncio.create_task(drive_bot(first_turn))
                    events = await asyncio.wait_for(read_sse(), timeout=20)
                    await asyncio.wait_for(driver, timeout=5)

    types = [e["type"] for e in events]
    assert "move" in types, types
    assert types[-1] == "game_over"
    # move events carry a renderable board + clocks
    a_move = next(e for e in events if e["type"] == "move")
    assert {"ply", "uci", "san", "fen", "clocks", "to_move"} <= set(a_move)
