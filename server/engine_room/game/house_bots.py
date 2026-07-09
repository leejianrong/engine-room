"""House bots (ADR-0022) — always present so newcomers get an instant first game
and the spectator lobby is never empty. Run in-process; never over a socket.

In V1 the house bot's mover is a simple RandomBot; in V7 the SDK's reference
bots become the house bots.
"""

from __future__ import annotations

import random

import chess

from ..protocol.messages import BotInfo

# Canonical identity of the built-in random house bot. Persisted as a `bots` row
# (owner NULL, is_house) so games' bot FKs resolve for house games (ADR-0022).
HOUSE_RANDOM_ID = "bot_house_random"
HOUSE_RANDOM_NAME = "house-random"
HOUSE_RANDOM_RATING = 1200

# A second house identity (ADR-0022 Kind-1 / V6 D-h): needed so ambient
# house-vs-house games have two distinct rated, persisted bots. Same random
# mover; seeded as a `bots` row by Alembic 0004 (and seed_house_bots).
HOUSE_RANDOM_2_ID = "bot_house_random_2"
HOUSE_RANDOM_2_NAME = "house-random-2"
HOUSE_RANDOM_2_RATING = 1200


class RandomBot:
    """Picks a uniformly-random legal move."""

    def __init__(
        self,
        id: str = HOUSE_RANDOM_ID,
        name: str = HOUSE_RANDOM_NAME,
        rating: int = HOUSE_RANDOM_RATING,
    ):
        self.info = BotInfo(id=id, name=name, rating=rating)

    def choose_move(self, board: chess.Board) -> str:
        return random.choice(list(board.legal_moves)).uci()
