"""V6 sub-step 2 (integration, real Postgres): a finished game is reconstructed
for replay from its stored PGN, and appears in the lobby's recently-finished list.

Uses httpx ASGITransport (plain JSON GETs — no streaming), with the app's
PostgresGameReader bound to the ephemeral testcontainer via the session_factory.
"""

from datetime import datetime, timezone

import chess
import chess.pgn
import httpx

from engine_room.app import create_app
from engine_room.persistence.models import Game as GameRow
from engine_room.persistence.reader import PostgresGameReader

SCHOLARS_MATE = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]


def _scholars_mate_pgn() -> tuple[str, str]:
    board = chess.Board()
    for uci in SCHOLARS_MATE:
        board.push_uci(uci)
    assert board.is_checkmate()
    return str(chess.pgn.Game.from_board(board)), board.fen()


async def _insert_finished_game(session_factory, game_id: str) -> str:
    pgn, final_fen = _scholars_mate_pgn()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                GameRow(
                    id=game_id,
                    result="white_wins",
                    termination="checkmate",
                    final_fen=final_fen,
                    pgn=pgn,
                    base_seconds=180,
                    increment_seconds=0,
                    white_bot_id=None,
                    black_bot_id=None,
                    white_name="alice",
                    black_name="bob",
                    white_rating_before=1200,
                    white_rating_after=1216,
                    black_rating_before=1200,
                    black_rating_after=1184,
                    created_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                )
            )
    return final_fen


def _app(session_factory):
    return create_app(game_reader=PostgresGameReader(session_factory))


async def test_finished_game_replay_reconstructs_moves_from_pgn(session_factory):
    app = _app(session_factory)
    final_fen = await _insert_finished_game(session_factory, "game_scholar")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/games/game_scholar")
    assert resp.status_code == 200
    view = resp.json()

    assert view["state"] == "finished"
    assert view["result"] == "white_wins"
    assert view["termination"] == "checkmate"
    assert view["final_fen"] == final_fen
    assert view["rating"] == {
        "white": {"before": 1200, "after": 1216},
        "black": {"before": 1200, "after": 1184},
    }

    # The move-list reconstructs the whole game with a per-ply FEN that matches a
    # fresh python-chess walk (the client's single replay model, D-d).
    moves = view["moves"]
    assert [m["uci"] for m in moves] == SCHOLARS_MATE
    board = chess.Board(view["initial_fen"])
    for i, m in enumerate(moves):
        assert m["ply"] == i
        assert board.san(chess.Move.from_uci(m["uci"])) == m["san"]
        board.push_uci(m["uci"])
        assert m["fen"] == board.fen()
    assert board.fen() == final_fen


async def test_finished_game_appears_in_lobby_list(session_factory):
    app = _app(session_factory)
    await _insert_finished_game(session_factory, "game_scholar2")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/games")
    assert resp.status_code == 200
    games = resp.json()["games"]
    entry = next(g for g in games if g["game_id"] == "game_scholar2")
    assert entry["state"] == "finished"
    assert entry["result"] == "white_wins"
    assert entry["white"] == {"name": "alice", "rating": 1216}
    assert entry["black"] == {"name": "bob", "rating": 1184}
    assert entry["finished_at"]
