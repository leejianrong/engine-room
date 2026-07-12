"""Reference bots that ship with the SDK.

These are the newcomer's examples (ADR-0022), one per rung of the tutorial ladder
(random → material-count → minimax → your own engine): ``RandomBot`` is the true
zero-chess-knowledge hello-world; ``GreedyBot`` is the "level 1" one-ply material
grabber; ``MinimaxBot`` is the "level 2" sample. Their move logic mirrors the
platform's house bots (``house-random`` / ``house-minimax``) — the "reference bots
double as house bots" intent — but by *shared behavior*, not a shared import
(ADR-0021 decoupling; see V7 O-1).
"""

from __future__ import annotations

import random

import chess

from . import _greedy, _minimax
from .bot import Bot


class RandomBot(Bot):
    """Plays a uniformly-random legal move. The hello-world bot."""

    def __init__(self, *args, seed: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rng = random.Random(seed)

    def choose_move(self, board: chess.Board) -> chess.Move:
        return self._rng.choice(list(board.legal_moves))


class GreedyBot(Bot):
    """Looks exactly one move ahead and grabs the move that maximizes its own
    material — the "material-count" rung between ``RandomBot`` and ``MinimaxBot``.
    It takes free/hanging pieces and the highest-value capture on offer, but has no
    lookahead, so it walks into recaptures. A great baseline to beat with search."""

    def __init__(self, *args, seed: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rng = random.Random(seed)

    def choose_move(self, board: chess.Board) -> str:
        return _greedy.choose_move(board, rng=self._rng)


class MinimaxBot(Bot):
    """Depth-limited minimax + alpha-beta (material + piece-square eval). A
    non-blundering "level 2" example that still fits a 3+0 clock."""

    def __init__(self, *args, depth: int = 3, seed: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.depth = depth
        self._rng = random.Random(seed)

    def choose_move(self, board: chess.Board) -> str:
        return _minimax.choose_move(board, depth=self.depth, rng=self._rng)
