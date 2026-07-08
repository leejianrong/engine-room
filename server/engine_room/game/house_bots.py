"""House bots (ADR-0022) — always present so newcomers get an instant first game
and the spectator lobby is never empty. Run in-process; never over a socket.

In V1 the house bot's mover is a simple RandomBot; in V7 the SDK's reference
bots become the house bots.
"""

from __future__ import annotations

import random

import chess

from ..protocol.messages import BotInfo


class RandomBot:
    """Picks a uniformly-random legal move."""

    def __init__(
        self, id: str = "bot_house_random", name: str = "house-random", rating: int = 1200
    ):
        self.info = BotInfo(id=id, name=name, rating=rating)

    def choose_move(self, board: chess.Board) -> str:
        return random.choice(list(board.legal_moves)).uci()
