"""Read side of the durable game record (V6, ADR-0015/0018) — anonymous,
read-only queries behind the spectator lobby + replay endpoints.

`PostgresGameReader` is injected into the app like `PostgresFinalizer` (see
create_app): production wires the real one; fast tests that don't touch the DB
leave it `None` and the endpoints degrade to the in-memory registry only.

The finished-game replay source is the stored **PGN** (ADR-0018): a game row is
projected into the same uniform `[{ply, san, uci, fen}]` move-list the live path
serves from `LiveState`, so the client has ONE replay model for both (V6 D-d).
"""

from __future__ import annotations

import io
from typing import Optional

import chess
import chess.pgn
from sqlalchemy import select

from .db import SessionLocal
from .models import Game as GameRow


def _moves_from_pgn(pgn: str) -> tuple[str, list[dict]]:
    """Parse a stored PGN into `(initial_fen, [{ply, san, uci, fen}])` by walking
    the mainline (python-chess is the rules authority, ADR-0006). `initial_fen`
    comes from the game's start position (standard at MVP; a SetUp/FEN header is
    honoured by `game.board()` if ever present)."""
    game = chess.pgn.read_game(io.StringIO(pgn)) if pgn else None
    if game is None:
        return chess.STARTING_FEN, []
    board = game.board()
    initial_fen = board.fen()
    moves: list[dict] = []
    for ply, move in enumerate(game.mainline_moves()):
        san = board.san(move)
        uci = move.uci()
        board.push(move)
        moves.append({"ply": ply, "san": san, "uci": uci, "fen": board.fen()})
    return initial_fen, moves


def _rating_block(row: GameRow) -> Optional[dict]:
    """The per-color Elo change written at finalize, or None for a game that was
    not rated (ABORTED — rating columns NULL)."""
    if row.white_rating_before is None or row.white_rating_after is None:
        return None
    return {
        "white": {"before": row.white_rating_before, "after": row.white_rating_after},
        "black": {"before": row.black_rating_before, "after": row.black_rating_after},
    }


def _lobby_entry(row: GameRow) -> dict:
    """A recently-finished game as a lobby list item (V6 D-e)."""
    return {
        "game_id": row.id,
        "state": "aborted" if row.result == "aborted" else "finished",
        "white": {"name": row.white_name, "rating": row.white_rating_after},
        "black": {"name": row.black_name, "rating": row.black_rating_after},
        "time_control": {
            "base_seconds": row.base_seconds,
            "increment_seconds": row.increment_seconds,
        },
        "ply": None,
        "to_move": None,
        "started_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "result": row.result,
        "termination": row.termination,
    }


def _game_view(row: GameRow) -> dict:
    """The full replay/detail view of a finished game (V6 D-d)."""
    initial_fen, moves = _moves_from_pgn(row.pgn)
    return {
        "game_id": row.id,
        "state": "aborted" if row.result == "aborted" else "finished",
        "white": {
            "name": row.white_name,
            "rating": row.white_rating_after,
            "bot_id": row.white_bot_id,
        },
        "black": {
            "name": row.black_name,
            "rating": row.black_rating_after,
            "bot_id": row.black_bot_id,
        },
        "time_control": {
            "base_seconds": row.base_seconds,
            "increment_seconds": row.increment_seconds,
        },
        "initial_fen": initial_fen,
        "moves": moves,
        "result": row.result,
        "termination": row.termination,
        "final_fen": row.final_fen,
        "rating": _rating_block(row),
    }


class PostgresGameReader:
    def __init__(self, session_factory=SessionLocal):
        self._session_factory = session_factory

    async def recent_finished(self, limit: int) -> list[dict]:
        """The most-recently-finished games (newest first), as lobby entries."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(GameRow).order_by(GameRow.finished_at.desc()).limit(limit)
            )
            return [_lobby_entry(row) for row in result.scalars().all()]

    async def get(self, game_id: str) -> Optional[dict]:
        """The full replay/detail view of one finished game, or None if unknown."""
        async with self._session_factory() as session:
            row = await session.get(GameRow, game_id)
            return _game_view(row) if row is not None else None
