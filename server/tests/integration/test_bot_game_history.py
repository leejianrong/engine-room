"""KAN-53 (integration, real Postgres): the per-bot game-history endpoint
`GET /api/bots/{bot_id}/games`.

A bot's FINISHED games are projected from THAT bot's perspective — result becomes
win/loss/draw for it (derived from the stored result + which colour it played),
the opponent is the other seat, and the rating change is this bot's own colour's
{before, after}. Aborted games and games the bot didn't play are excluded, and
the summary W/L/D is aggregated over all of its decided games. Mirrors
test_v6_lobby_replay's ASGITransport + injected PostgresGameReader wiring.
"""

from datetime import datetime, timedelta, timezone

import httpx

from engine_room.app import create_app
from engine_room.persistence.models import Bot as BotRow
from engine_room.persistence.models import Game as GameRow
from engine_room.persistence.reader import PostgresGameReader

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _bot(bot_id: str, name: str, rating: int = 1200, games_played: int = 0) -> BotRow:
    return BotRow(
        id=bot_id,
        owner_id=None,
        name=name,
        description="",
        rating=rating,
        games_played=games_played,
        is_house=False,
        created_at=_T0,
    )


def _game(
    game_id: str,
    *,
    result: str,
    termination: str,
    white_id: str | None,
    black_id: str | None,
    white_name: str,
    black_name: str,
    minutes: int,
    white_before: int | None = None,
    white_after: int | None = None,
    black_before: int | None = None,
    black_after: int | None = None,
    base_seconds: int = 180,
) -> GameRow:
    return GameRow(
        id=game_id,
        result=result,
        termination=termination,
        final_fen="8/8/8/8/8/8/8/8 w - - 0 1",
        pgn="",
        base_seconds=base_seconds,
        increment_seconds=0,
        white_bot_id=white_id,
        black_bot_id=black_id,
        white_name=white_name,
        black_name=black_name,
        white_rating_before=white_before,
        white_rating_after=white_after,
        black_rating_before=black_before,
        black_rating_after=black_after,
        created_at=_T0 + timedelta(minutes=minutes),
        finished_at=_T0 + timedelta(minutes=minutes + 1),
    )


async def _seed(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add_all(
                [
                    _bot("bot_hero", "hero", rating=1250, games_played=5),
                    _bot("bot_villain", "villain", rating=1300),
                    # game 1: hero white, wins
                    _game(
                        "game_1",
                        result="white_wins",
                        termination="checkmate",
                        white_id="bot_hero",
                        black_id="bot_villain",
                        white_name="hero",
                        black_name="villain",
                        minutes=10,
                        white_before=1240,
                        white_after=1250,
                        black_before=1310,
                        black_after=1300,
                    ),
                    # game 2: hero black, white wins → hero loses
                    _game(
                        "game_2",
                        result="white_wins",
                        termination="resignation",
                        white_id="bot_villain",
                        black_id="bot_hero",
                        white_name="villain",
                        black_name="hero",
                        minutes=20,
                        white_before=1290,
                        white_after=1300,
                        black_before=1260,
                        black_after=1250,
                    ),
                    # game 3: hero black, black wins → hero wins
                    _game(
                        "game_3",
                        result="black_wins",
                        termination="timeout",
                        white_id="bot_villain",
                        black_id="bot_hero",
                        white_name="villain",
                        black_name="hero",
                        minutes=30,
                    ),
                    # game 4: hero white, draw
                    _game(
                        "game_4",
                        result="draw",
                        termination="agreement",
                        white_id="bot_hero",
                        black_id="bot_villain",
                        white_name="hero",
                        black_name="villain",
                        minutes=40,
                    ),
                    # game 5: hero white, aborted → excluded (no W/L/D)
                    _game(
                        "game_5",
                        result="aborted",
                        termination="abandoned",
                        white_id="bot_hero",
                        black_id="bot_villain",
                        white_name="hero",
                        black_name="villain",
                        minutes=50,
                    ),
                    # game 6: hero not involved → excluded
                    _game(
                        "game_6",
                        result="white_wins",
                        termination="checkmate",
                        white_id="bot_villain",
                        black_id=None,
                        white_name="villain",
                        black_name="ghost",
                        minutes=60,
                    ),
                ]
            )


def _app(session_factory):
    return create_app(game_reader=PostgresGameReader(session_factory))


async def test_bot_history_summary_and_perspective(session_factory):
    await _seed(session_factory)
    app = _app(session_factory)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/bots/bot_hero/games")
    assert resp.status_code == 200
    body = resp.json()

    assert body["bot"] == {"bot_id": "bot_hero", "name": "hero"}
    # 2 wins (game_1 white, game_3 black), 1 loss (game_2), 1 draw (game_4);
    # aborted + not-involved games excluded. games_played/rating come off the row.
    assert body["summary"] == {
        "wins": 2,
        "losses": 1,
        "draws": 1,
        "games_played": 5,
        "rating": 1250,
    }

    games = body["games"]
    assert [g["game_id"] for g in games] == ["game_4", "game_3", "game_2", "game_1"]

    by_id = {g["game_id"]: g for g in games}

    # game_1: hero white, win, own rating change, opponent = villain (post rating).
    g1 = by_id["game_1"]
    assert g1["color"] == "white"
    assert g1["result"] == "win"
    assert g1["rating"] == {"before": 1240, "after": 1250}
    assert g1["opponent"] == {"bot_id": "bot_villain", "name": "villain", "rating": 1300}
    assert g1["termination"] == "checkmate"
    assert g1["time_control"] == {"base_seconds": 180, "increment_seconds": 0}
    assert g1["finished_at"]

    # game_2: hero black, loss, own (black) rating change.
    g2 = by_id["game_2"]
    assert g2["color"] == "black"
    assert g2["result"] == "loss"
    assert g2["rating"] == {"before": 1260, "after": 1250}
    assert g2["opponent"]["name"] == "villain"

    # game_3: hero black, win; this game stored no rating → null rating block.
    g3 = by_id["game_3"]
    assert g3["color"] == "black"
    assert g3["result"] == "win"
    assert g3["rating"] is None

    # game_4: hero white, draw.
    assert by_id["game_4"]["result"] == "draw"


async def test_bot_history_limit_trims_list_not_summary(session_factory):
    await _seed(session_factory)
    app = _app(session_factory)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/bots/bot_hero/games?limit=2")
    assert resp.status_code == 200
    body = resp.json()

    # Only the 2 newest decided games are listed...
    assert [g["game_id"] for g in body["games"]] == ["game_4", "game_3"]
    # ...but the summary still reflects all decided games.
    assert body["summary"]["wins"] == 2
    assert body["summary"]["losses"] == 1
    assert body["summary"]["draws"] == 1


async def test_bot_with_no_finished_games(session_factory):
    async with session_factory() as session:
        async with session.begin():
            session.add(_bot("bot_fresh", "fresh"))
    app = _app(session_factory)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/bots/bot_fresh/games")
    assert resp.status_code == 200
    body = resp.json()
    assert body["games"] == []
    assert body["summary"] == {
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "games_played": 0,
        "rating": 1200,
    }


async def test_unknown_bot_is_404(session_factory):
    app = _app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/bots/bot_nope/games")
    assert resp.status_code == 404
