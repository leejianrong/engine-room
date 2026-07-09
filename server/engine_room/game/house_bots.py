"""House bots (ADR-0022) — always present so newcomers get an instant first game
and the spectator lobby is never empty. Run in-process; never over a socket.

Two roles / two personas (post-MVP house-bot personas change):

- **`ephraim-bot`** — the *ephemeral greeter* (Kind-2). Synthesized on demand for
  a lone seeker, plays one game, then it's gone; a deliberately **easy, random**
  first opponent. Its rating drift doesn't matter (it isn't a lobby resident).
- **`jian-bot-001` / `jian-bot-002`** — the *permanent* ambient bots (Kind-1) that
  live in the lobby 24/7, rated and persisted like real bots. They play **minimax
  + alpha-beta** (`game.minimax`), so lobby games look like real chess.

Movers are duck-typed: anything with `.info` (a `BotInfo`) and
`choose_move(board) -> uci` drops into the seat machinery (`HouseSeat`).
"""

from __future__ import annotations

import random

import chess

from ..protocol.messages import BotInfo
from . import minimax

# --- ephemeral greeter (Kind-2): easy, random, one-and-done -------------------
EPHRAIM_ID = "bot_ephraim"
EPHRAIM_NAME = "ephraim-bot"
EPHRAIM_RATING = 1200

# --- permanent ambient bots (Kind-1): minimax, rated, lobby residents ---------
# IDs are historical (these rows were the V3/V6 "house-random" / "house-random-2")
# — kept stable so existing games' FKs and history survive; only the display name
# and mover changed. Migration 0005 renames the rows + seeds ephraim.
JIAN_001_ID = "bot_house_random"
JIAN_001_NAME = "jian-bot-001"
JIAN_001_RATING = 1200
JIAN_002_ID = "bot_house_random_2"
JIAN_002_NAME = "jian-bot-002"
JIAN_002_RATING = 1200


class RandomBot:
    """Picks a uniformly-random legal move — the easy greeter persona (ephraim)."""

    def __init__(
        self,
        id: str = EPHRAIM_ID,
        name: str = EPHRAIM_NAME,
        rating: int = EPHRAIM_RATING,
    ):
        self.info = BotInfo(id=id, name=name, rating=rating)

    def choose_move(self, board: chess.Board) -> str:
        return random.choice(list(board.legal_moves)).uci()


class MinimaxBot:
    """Plays depth-limited minimax + alpha-beta (`game.minimax`) — the permanent
    ambient persona (jian-bot-NNN). Same `choose_move(board) -> uci` interface as
    `RandomBot`, so it drops into the same seat/ambient machinery."""

    def __init__(
        self,
        id: str = JIAN_001_ID,
        name: str = JIAN_001_NAME,
        rating: int = JIAN_001_RATING,
        *,
        depth: int = 3,
    ):
        self.info = BotInfo(id=id, name=name, rating=rating)
        self.depth = depth

    def choose_move(self, board: chess.Board) -> str:
        return minimax.choose_move(board, depth=self.depth)
