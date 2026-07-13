"""A small minimax + alpha-beta move engine (material + piece-square eval).

A pure `choose_move(board) -> uci` — the same interface `RandomBot` exposes — so
it drops into the existing seat/house machinery. It is the engine behind the
ambient lobby residents `jian-bot-001/002` (`MinimaxBot` in `house_bots.py`), so
house-vs-house lobby games look like real chess; the dev demo client reuses it too.

Depth 3 with capture-first ordering is ~0.1-0.3s/move in pure Python — sensible,
non-blundering play without lagging a 3+0 clock. Piece-square tables are the
well-known "simplified evaluation" values (Michniewski), laid out a8→h1.
"""

from __future__ import annotations

import random

import chess

MATE = 1_000_000
INF = 10_000_000
# Contempt (centipawns): how much the bot dislikes steering into a draw. Small on
# purpose — an equal-or-better bot avoids sterile repetition/fifty-move shuffling
# (which was making lobby games peter out into threefold), but a *losing* bot
# still grabs the saving draw, since a drawn line at -CONTEMPT beats a lost one.
CONTEMPT = 40

# Centipawn material values (king has no material value — mate is scored separately).
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# Piece-square tables, White's perspective, index 0 = a8 … 63 = h1.
_PAWN = [
      0,   0,   0,   0,   0,   0,   0,   0,
     50,  50,  50,  50,  50,  50,  50,  50,
     10,  10,  20,  30,  30,  20,  10,  10,
      5,   5,  10,  25,  25,  10,   5,   5,
      0,   0,   0,  20,  20,   0,   0,   0,
      5,  -5, -10,   0,   0, -10,  -5,   5,
      5,  10,  10, -20, -20,  10,  10,   5,
      0,   0,   0,   0,   0,   0,   0,   0,
]
_KNIGHT = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   0,   0,   0, -20, -40,
    -30,   0,  10,  15,  15,  10,   0, -30,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -30,   0,  15,  20,  20,  15,   0, -30,
    -30,   5,  10,  15,  15,  10,   5, -30,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]
_BISHOP = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,  10,  10,   5,   0, -10,
    -10,   5,   5,  10,  10,   5,   5, -10,
    -10,   0,  10,  10,  10,  10,   0, -10,
    -10,  10,  10,  10,  10,  10,  10, -10,
    -10,   5,   0,   0,   0,   0,   5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]
_ROOK = [
      0,   0,   0,   0,   0,   0,   0,   0,
      5,  10,  10,  10,  10,  10,  10,   5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
      0,   0,   0,   5,   5,   0,   0,   0,
]
_QUEEN = [
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,   5,   5,   5,   0, -10,
     -5,   0,   5,   5,   5,   5,   0,  -5,
      0,   0,   5,   5,   5,   5,   0,  -5,
    -10,   5,   5,   5,   5,   5,   0, -10,
    -10,   0,   5,   0,   0,   0,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20,
]
_KING = [
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
     20,  20,   0,   0,   0,   0,  20,  20,
     20,  30,  10,   0,   0,  10,  30,  20,
]
_PST = {
    chess.PAWN: _PAWN,
    chess.KNIGHT: _KNIGHT,
    chess.BISHOP: _BISHOP,
    chess.ROOK: _ROOK,
    chess.QUEEN: _QUEEN,
    chess.KING: _KING,
}

_module_rng = random.Random()


def _pst_value(table: list[int], square: int, color: chess.Color) -> int:
    file = chess.square_file(square)
    rank = chess.square_rank(square)  # 0 = rank 1
    # Tables are a8-first; a White piece reads top-down, Black mirrors vertically.
    idx = (7 - rank) * 8 + file if color == chess.WHITE else rank * 8 + file
    return table[idx]


def evaluate(board: chess.Board) -> int:
    """Static evaluation in centipawns, positive = better for White."""
    score = 0
    for square, piece in board.piece_map().items():
        value = PIECE_VALUES[piece.piece_type] + _pst_value(
            _PST[piece.piece_type], square, piece.color
        )
        score += value if piece.color == chess.WHITE else -value
    return score


def _ordered_moves(board: chess.Board) -> list[chess.Move]:
    # Captures first — cheap ordering that sharpens alpha-beta pruning.
    return sorted(board.legal_moves, key=board.is_capture, reverse=True)


def _search(board: chess.Board, depth: int, alpha: int, beta: int) -> int:
    """Negamax with alpha-beta; returns the score for the side to move."""
    if depth == 0:
        s = evaluate(board)
        return s if board.turn == chess.WHITE else -s
    moves = _ordered_moves(board)
    if not moves:  # no legal move → checkmate (bad) or stalemate (draw)
        return -MATE if board.is_check() else 0
    best = -INF
    for move in moves:
        board.push(move)
        val = -_search(board, depth - 1, -beta, -alpha)
        board.pop()
        if val > best:
            best = val
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def choose_move(board: chess.Board, depth: int = 3, rng: random.Random | None = None) -> str:
    """Pick a move by depth-limited minimax; return its UCI string.

    Root moves are scored with a full window (exact values) so equally-best moves
    can be collected and one chosen at random — a little variety across a looping
    demo without ever preferring a worse move."""
    rng = rng or _module_rng
    moves = _ordered_moves(board)
    if not moves:
        raise ValueError("no legal moves")
    best_val = -INF
    best_moves: list[chess.Move] = []
    for move in moves:
        board.push(move)
        # A move that forces a draw the server will auto-claim (threefold or the
        # fifty-move rule) ends the game *here*, so value it as the draw itself —
        # nudged by contempt to -CONTEMPT — instead of by the material on the board.
        # A winning bot then shuns the draw (a real edge beats -CONTEMPT); a losing
        # bot still grabs it (-CONTEMPT beats a lost line). This is why lobby games
        # stopped petering out into threefold. Root-only, so it stays cheap.
        if board.is_repetition(3) or board.halfmove_clock >= 100:
            val = -CONTEMPT
        else:
            val = -_search(board, depth - 1, -INF, INF)
        board.pop()
        if val > best_val:
            best_val, best_moves = val, [move]
        elif val == best_val:
            best_moves.append(move)
    return rng.choice(best_moves).uci()
