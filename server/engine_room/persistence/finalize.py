"""Atomic finalization (N8, ADR-0018/0025).

At game end the durable record is written to Postgres in a single transaction.
V1 writes one `games` row; V5 adds rating updates to the same transaction so a
bot's history and rating can never disagree.

`PostgresFinalizer` is injected into the game loop (see create_app / run_game),
so tests that don't care about persistence run without a database.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .db import SessionLocal
from .models import Game as GameRow


class PostgresFinalizer:
    def __init__(self, session_factory=SessionLocal):
        self._session_factory = session_factory

    async def __call__(
        self, game, result: str, termination: str, final_fen: str, pgn: str
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():  # one transaction
                session.add(
                    GameRow(
                        id=game.id,
                        result=result,
                        termination=termination,
                        final_fen=final_fen,
                        pgn=pgn,
                        base_seconds=game.time_control.base_seconds,
                        increment_seconds=game.time_control.increment_seconds,
                        white_name=game.white.bot.name,
                        black_name=game.black.bot.name,
                        created_at=game.created_at,
                        finished_at=datetime.now(timezone.utc),
                    )
                )
