"""Minimax move engine: eval symmetry + tactically sound choices (no infra)."""

import random

import chess

from engine_room.game.minimax import choose_move, evaluate


def test_start_position_is_balanced():
    assert evaluate(chess.Board()) == 0  # symmetric material + PST → 0


def test_choose_move_returns_a_legal_move():
    board = chess.Board()
    uci = choose_move(board, depth=2, rng=random.Random(0))
    assert chess.Move.from_uci(uci) in board.legal_moves


def test_finds_mate_in_one():
    # Black king a8; White Kb6 + Rh7. Rh8# is mate.
    board = chess.Board("k7/7R/1K6/8/8/8/8/8 w - - 0 1")
    assert choose_move(board, depth=3) == "h7h8"


def test_grabs_a_free_queen():
    # White rook e4 can capture the undefended black queen on e5.
    board = chess.Board("7k/8/8/4q3/4R3/8/8/7K w - - 0 1")
    assert choose_move(board, depth=3) == "e4e5"


def test_prefers_winning_material_over_a_quiet_move():
    # White to move: capturing the hanging rook is clearly best.
    board = chess.Board("7k/8/8/8/3r4/8/3R4/7K w - - 0 1")  # Rd2 x Rd4 down the file
    assert choose_move(board, depth=3) == "d2d4"
