"""V6 sub-step 2 (unit, DB-free): the lobby list + replay/detail endpoints served
from the in-memory registry (no game_reader injected → active-only lobby, in-memory
detail, 404 for unknown)."""

import httpx

from engine_room.app import create_app
from engine_room.game.game import Participant
from engine_room.game.house_bots import RandomBot
from engine_room.game.worker import prepare_game
from engine_room.protocol.messages import TimeControl


def _running_house_game(app):
    reg = app.state.game_registry
    h1 = RandomBot(id="bot_h1", name="alice", rating=1300)
    h2 = RandomBot(id="bot_h2", name="bob", rating=1100)
    game = reg.create_game(
        white=Participant(bot=h1.info, is_house=True, house=h1),
        black=Participant(bot=h2.info, is_house=True, house=h2),
        time_control=TimeControl(base_seconds=180),
    )
    prepare_game(game)
    game.state = "in_progress"
    # Simulate 1. e4 played.
    live = game.live
    live.board.push_uci("e2e4")
    live.last_move = {"uci": "e2e4", "san": "e4"}
    live.moves.append({"ply": 0, "uci": "e2e4", "san": "e4", "fen": live.board.fen()})
    live.ply = 1
    return game


async def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    )


async def test_lobby_lists_active_game():
    app = create_app()  # no game_reader → active-only
    game = _running_house_game(app)
    async with await _client(app) as client:
        resp = await client.get("/api/games")
    assert resp.status_code == 200
    games = resp.json()["games"]
    entry = next(g for g in games if g["game_id"] == game.id)
    assert entry["state"] == "in_progress"
    assert entry["white"] == {"name": "alice", "rating": 1300}
    assert entry["black"] == {"name": "bob", "rating": 1100}
    assert entry["ply"] == 1
    assert entry["to_move"] == "black"
    assert entry["time_control"] == {"base_seconds": 180, "increment_seconds": 0}
    assert entry["started_at"]


async def test_lobby_empty_when_no_games():
    app = create_app()
    async with await _client(app) as client:
        resp = await client.get("/api/games")
    assert resp.status_code == 200
    assert resp.json()["games"] == []


async def test_game_detail_of_live_game_projects_moves():
    app = create_app()
    game = _running_house_game(app)
    async with await _client(app) as client:
        resp = await client.get(f"/api/games/{game.id}")
    assert resp.status_code == 200
    view = resp.json()
    assert view["game_id"] == game.id
    assert view["state"] == "in_progress"
    assert view["white"]["bot_id"] == "bot_h1"
    assert view["initial_fen"].startswith("rnbqkbnr/pppppppp")
    assert view["moves"] == [
        {"ply": 0, "uci": "e2e4", "san": "e4", "fen": game.live.board.fen()}
    ]
    assert view["result"] is None
    assert view["rating"] is None


async def test_game_detail_unknown_is_404():
    app = create_app()
    async with await _client(app) as client:
        resp = await client.get("/api/games/game_nope")
    assert resp.status_code == 404
