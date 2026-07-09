"""Atomic finalization (N8, ADR-0018/0025).

At game end the durable record is written to Postgres in a single transaction.
V5 computes the Elo update in that **same** transaction (ADR-0025 #5): the `games`
row (incl. per-color rating before/after) and both `bots.rating`/`games_played`
updates commit together, so a crash can never desync ratings from saved games.

`PostgresFinalizer` returns a `FinalizeResult` carrying each side's `(before,
after)` so the game loop can put the *persisted* numbers into `game_over.rating`.
An ABORTED game has no result → no rating: the row's rating columns stay NULL and
`__call__` returns None. When no finalizer is injected (DB-free tests / the
house-direct path), the loop falls back to a stubbed rating.

`PostgresFinalizer` is injected into the game loop (see create_app / run_game),
so tests that don't care about persistence run without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from ..game import ratings
from .db import SessionLocal
from .models import Bot as BotRow
from .models import Game as GameRow


@dataclass
class FinalizeResult:
    """Per-color persisted Elo change, for `game_over.rating` (PROTOCOL §8)."""

    white: tuple[int, int]  # (before, after)
    black: tuple[int, int]


class PostgresFinalizer:
    def __init__(
        self,
        session_factory=SessionLocal,
        *,
        k_provisional: int | None = None,
        k_default: int | None = None,
        provisional_games: int | None = None,
    ):
        self._session_factory = session_factory
        self._k_provisional = k_provisional or settings.elo_k_provisional
        self._k_default = k_default or settings.elo_k_default
        self._provisional_games = provisional_games or settings.elo_provisional_games

    def _new_rating(self, rating: int, opponent: int, score: float, games_played: int) -> int:
        k = ratings.k_factor(
            games_played,
            provisional_k=self._k_provisional,
            default_k=self._k_default,
            provisional_games=self._provisional_games,
        )
        return ratings.updated(rating, opponent, score, k)

    async def __call__(
        self, game, result: str, termination: str, final_fen: str, pgn: str
    ) -> Optional[FinalizeResult]:
        async with self._session_factory() as session:
            async with session.begin():  # one transaction (result + Elo + PGN)
                rating_cols: dict[str, int | None] = {
                    "white_rating_before": None,
                    "white_rating_after": None,
                    "black_rating_before": None,
                    "black_rating_after": None,
                }
                outcome: Optional[FinalizeResult] = None

                # ABORTED games have no fair result → no rating (ADR-0010/0011).
                if result != "aborted":
                    white = await session.get(BotRow, game.white.bot.id)
                    black = await session.get(BotRow, game.black.bot.id)
                    if white is not None and black is not None:
                        w0, b0 = white.rating, black.rating
                        wc, bc = ratings.scores(result)
                        wa = self._new_rating(w0, b0, wc, white.games_played)
                        ba = self._new_rating(b0, w0, bc, black.games_played)
                        # Rate both bots uniformly (house included, Q3).
                        white.rating, black.rating = wa, ba
                        white.games_played += 1
                        black.games_played += 1
                        rating_cols = {
                            "white_rating_before": w0,
                            "white_rating_after": wa,
                            "black_rating_before": b0,
                            "black_rating_after": ba,
                        }
                        outcome = FinalizeResult(white=(w0, wa), black=(b0, ba))

                session.add(
                    GameRow(
                        id=game.id,
                        result=result,
                        termination=termination,
                        final_fen=final_fen,
                        pgn=pgn,
                        base_seconds=game.time_control.base_seconds,
                        increment_seconds=game.time_control.increment_seconds,
                        white_bot_id=game.white.bot.id,  # V2 FKs (ADR-0009)
                        black_bot_id=game.black.bot.id,
                        white_name=game.white.bot.name,  # denormalized snapshot
                        black_name=game.black.bot.name,
                        created_at=game.created_at,
                        finished_at=datetime.now(timezone.utc),
                        **rating_cols,
                    )
                )
                return outcome
