"""V1 sub-step 5: the worker publishes spectator events; SSE endpoint basics.

The end-to-end "SSE streams a live game" check lives in test_v1_spectate_live.py
against a real server (httpx's ASGITransport buffers the whole body, so it can't
exercise concurrent streaming).
"""

import httpx

from engine_room.app import create_app
from engine_room.channels import game_channel
from engine_room.game.game import Participant
from engine_room.game.house_bots import RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import run_game
from engine_room.protocol.messages import TimeControl
from engine_room.pubsub.inproc import InProcPubSub


def _house_game(registry: GameRegistry):
    h1 = RandomBot(id="bot_h1", name="alice")
    h2 = RandomBot(id="bot_h2", name="bob")
    return registry.create_game(
        white=Participant(bot=h1.info, is_house=True, house=h1),
        black=Participant(bot=h2.info, is_house=True, house=h2),
        time_control=TimeControl(base_seconds=180),
    )


async def test_worker_publishes_game_events():
    pubsub = InProcPubSub()
    registry = GameRegistry()
    game = _house_game(registry)

    sub = pubsub.subscribe(game_channel(game.id))
    result, termination = await run_game(game, pubsub)

    events = []
    while True:  # all events are already queued now that run_game returned
        ev = await sub.get()
        events.append(ev)
        if ev["type"] == "game_over":
            break

    assert events[0]["type"] == "game_start"
    assert events[0]["white"] == {"name": "alice", "rating": 1200}
    assert events[0]["initial_fen"].startswith("rnbqkbnr/pppppppp")

    moves = [e for e in events if e["type"] == "move"]
    assert len(moves) >= 1
    first = moves[0]
    assert first["ply"] == 0
    assert {"uci", "san", "fen", "clocks", "to_move"} <= set(first)
    assert first["to_move"] == "black"  # White has moved

    assert events[-1]["type"] == "game_over"
    assert events[-1]["result"] == result
    assert events[-1]["termination"] == termination


async def test_sse_unknown_game_is_404():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/api/spectate/game_nope")
    assert resp.status_code == 404
