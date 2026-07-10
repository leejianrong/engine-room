"""Reference bots that ship with the SDK.

These are the newcomer's examples (ADR-0022): ``RandomBot`` is the true zero-chess-
knowledge hello-world; ``MinimaxBot`` is the "level 2" sample. Their move logic
mirrors the platform's house bots (``house-random`` / ``house-minimax``) — the
"reference bots double as house bots" intent — but by *shared behavior*, not a
shared import (ADR-0021 decoupling; see V7 O-1).
"""

from __future__ import annotations

import random

import chess

from . import _minimax
from .bot import Bot


class RandomBot(Bot):
    """Plays a uniformly-random legal move. The hello-world bot."""

    def __init__(self, *args, seed: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rng = random.Random(seed)

    def choose_move(self, board: chess.Board) -> chess.Move:
        return self._rng.choice(list(board.legal_moves))


class MinimaxBot(Bot):
    """Depth-limited minimax + alpha-beta (material + piece-square eval). A
    non-blundering "level 2" example that still fits a 3+0 clock."""

    def __init__(self, *args, depth: int = 3, seed: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.depth = depth
        self._rng = random.Random(seed)

    def choose_move(self, board: chess.Board) -> str:
        return _minimax.choose_move(board, depth=self.depth, rng=self._rng)
