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
        # V4: bot_id -> its live in-progress game, so a reconnecting bot's seat can
        # be found (welcome.active_game + rebind) and inbound moves can be routed.
        # House bots (no session) are never indexed. Set at launch, cleared at end.
        self._active_by_bot: dict[str, Game] = {}
        # bot_id -> its most recently finished/aborted game, so a bot that missed
        # game_over while disconnected can be told the outcome on reconnect (D-vi).
        self._recent_terminal_by_bot: dict[str, Game] = {}

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

    # --- V4 active-game index (real, session-backed seats only) ---------------

    def bind_active(self, game: Game) -> None:
        """Mark `game` as the live game for each of its real bots (at launch)."""
        for participant in (game.white, game.black):
            if participant.session is not None:
                self._active_by_bot[participant.bot.id] = game

    def unbind_active(self, game: Game) -> None:
        """Clear the live-game binding at terminal and record it as this bot's
        most recent terminal (so reconnect can deliver a missed game_over)."""
        for participant in (game.white, game.black):
            if participant.session is None:
                continue
            bot_id = participant.bot.id
            if self._active_by_bot.get(bot_id) is game:
                del self._active_by_bot[bot_id]
            self._recent_terminal_by_bot[bot_id] = game

    def active_game_for(self, bot_id: str) -> Optional[Game]:
        return self._active_by_bot.get(bot_id)

    def recent_terminal_for(self, bot_id: str) -> Optional[Game]:
        return self._recent_terminal_by_bot.get(bot_id)

    def clear_recent_terminal(self, bot_id: str) -> None:
        """Drop a recent terminal once delivered on reconnect (D-vi)."""
        self._recent_terminal_by_bot.pop(bot_id, None)
