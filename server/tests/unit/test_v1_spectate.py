"""V1 sub-step 5: the worker publishes spectator events; SSE endpoint basics.

The end-to-end "SSE streams a live game" check lives in test_v1_spectate_live.py
against a real server (httpx's ASGITransport buffers the whole body, so it can't
exercise concurrent streaming).
"""

import json

import httpx

from engine_room.app import create_app
from engine_room.channels import game_channel
from engine_room.game.game import Participant
from engine_room.game.house_bots import RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import prepare_game, run_game
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


# --- V6 catch-up snapshot (D-a/D-b/D-c) --------------------------------------


def test_spectator_snapshot_shape():
    reg = GameRegistry()
    game = _house_game(reg)
    prepare_game(game)
    live = game.live
    # Simulate 1. e4 having been played (as the loop would record it).
    live.board.push_uci("e2e4")
    live.last_move = {"uci": "e2e4", "san": "e4"}
    live.moves.append({"ply": 0, "uci": "e2e4", "san": "e4", "fen": live.board.fen()})
    live.ply = 1
    game.state = "in_progress"

    snap = game.spectator_snapshot()
    assert snap["type"] == "snapshot"
    assert snap["game_id"] == game.id
    assert snap["state"] == "in_progress"
    assert snap["white"] == {"name": "alice", "rating": 1200}
    assert snap["black"] == {"name": "bob", "rating": 1200}
    assert snap["ply"] == 1
    assert snap["to_move"] == "black"
    assert snap["last_move"] == {"uci": "e2e4", "san": "e4"}
    assert snap["clocks"] == {"white_ms": 180000, "black_ms": 180000}
    assert snap["moves"] == [
        {"ply": 0, "uci": "e2e4", "san": "e4", "fen": live.board.fen()}
    ]
    assert snap["result"] is None and snap["termination"] is None


def test_spectator_snapshot_none_before_live():
    reg = GameRegistry()
    game = _house_game(reg)  # created, not yet prepared → no live state
    assert game.spectator_snapshot() is None


async def test_worker_records_live_move_history():
    """The loop appends every applied move to live.moves (the replay source)."""
    pubsub = InProcPubSub()
    reg = GameRegistry()
    game = _house_game(reg)
    await run_game(game, pubsub)
    moves = game.live.moves
    assert len(moves) >= 1
    assert [m["ply"] for m in moves] == list(range(len(moves)))  # 0,1,2,…
    assert {"ply", "uci", "san", "fen"} <= set(moves[0])


async def test_sse_of_finished_game_emits_snapshot_then_game_over():
    """Joining a finished-but-in-memory game via SSE: snapshot first (with the
    full move list for replay), then game_over — the stream ends, no hang."""
    app = create_app()
    reg = app.state.game_registry
    pubsub = app.state.pubsub
    game = _house_game(reg)
    result, termination = await run_game(game, pubsub, registry=reg)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get(f"/api/spectate/{game.id}")
    assert resp.status_code == 200
    events = [
        json.loads(line[len("data:"):].strip())
        for line in resp.text.splitlines()
        if line.startswith("data:")
    ]
    assert events[0]["type"] == "snapshot"
    assert events[0]["state"] == "finished"
    assert len(events[0]["moves"]) == len(game.live.moves) >= 1
    assert events[-1]["type"] == "game_over"
    assert events[-1]["result"] == result
    assert events[-1]["termination"] == termination
