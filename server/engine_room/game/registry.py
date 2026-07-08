"""In-memory registry of active games (single-process MVP, ADR-0020)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..ids import new_id
from ..protocol.messages import TimeControl
from .game import STANDARD_START_FEN, Game, Participant


class GameRegistry:
    def __init__(self) -> None:
        self._games: dict[str, Game] = {}

    def create_game(
        self, white: Participant, black: Participant, time_control: TimeControl
    ) -> Game:
        base_ms = time_control.base_seconds * 1000
        game = Game(
            id=new_id("game"),
            white=white,
            black=black,
            time_control=time_control,
            initial_fen=STANDARD_START_FEN,
            white_ms=base_ms,
            black_ms=base_ms,
            created_at=datetime.now(timezone.utc),
            state="paired",
        )
        self._games[game.id] = game
        return game

    def get(self, game_id: str) -> Optional[Game]:
        return self._games.get(game_id)
