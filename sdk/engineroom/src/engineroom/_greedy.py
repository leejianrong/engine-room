"""A one-ply, material-counting ("greedy") move engine.

The natural rung between ``RandomBot`` and ``MinimaxBot`` in the tutorial ladder
(random → material-count → minimax → your own engine): it looks exactly one move
ahead and grabs the move that leaves it with the most material, so it snaps up
free/hanging pieces and takes the highest-value capture on offer. It has no
lookahead beyond that single ply, so it will happily walk into recaptures — which
is precisely why the next rung (minimax) exists.

Material only (no piece-square tables); mate-in-one is still preferred via a large
terminal bonus. Standard centipawn piece values.
"""

from __future__ import annotations

import random

import chess

MATE = 1_000_000

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

_module_rng = random.Random()


def material(board: chess.Board) -> int:
    """Net material in centipawns from White's point of view."""
    score = 0
    for piece in board.piece_map().values():
        value = PIECE_VALUES[piece.piece_type]
        score += value if piece.color == chess.WHITE else -value
    return score


def _score_after(board: chess.Board, move: chess.Move) -> int:
    """Material from the mover's point of view after playing ``move``."""
    mover = board.turn
    board.push(move)
    try:
        if board.is_checkmate():
            return MATE
        score = material(board)
    finally:
        board.pop()
    return score if mover == chess.WHITE else -score


def choose_move(board: chess.Board, rng: random.Random | None = None) -> str:
    """Pick the move that maximizes the mover's material after one ply.

    Returns the move as a UCI string. Ties are broken uniformly at random so the
    bot doesn't play deterministically.
    """
    rng = rng or _module_rng
    moves = list(board.legal_moves)
    if not moves:
        raise ValueError("no legal moves")
    best_val = -MATE - 1
    best_moves: list[chess.Move] = []
    for move in moves:
        val = _score_after(board, move)
        if val > best_val:
            best_val, best_moves = val, [move]
        elif val == best_val:
            best_moves.append(move)
    return rng.choice(best_moves).uci()
