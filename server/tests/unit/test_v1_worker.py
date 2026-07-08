"""Deterministic unit tests for the worker's outcome mapping + PGN rendering.

Random house-vs-house games don't reliably reach checkmate, so the decisive
result/termination mapping is pinned here with fabricated positions.
"""

import chess

from engine_room.game.game import Participant
from engine_room.game.house_bots import RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import _outcome_to_result, _render_pgn
from engine_room.protocol.messages import TimeControl


def test_checkmate_maps_to_winner():
    board = chess.Board()
    for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):  # fool's mate — Black wins
        board.push_uci(uci)
    outcome = board.outcome()
    assert outcome is not None and outcome.termination == chess.Termination.CHECKMATE
    assert _outcome_to_result(outcome) == ("black_wins", "checkmate")


def test_stalemate_maps_to_draw():
    board = chess.Board("7k/8/5KQ1/8/8/8/8/8 b - - 0 1")
    outcome = board.outcome()
    assert outcome is not None and outcome.termination == chess.Termination.STALEMATE
    assert _outcome_to_result(outcome) == ("draw", "stalemate")


def test_insufficient_material_maps_to_draw():
    board = chess.Board("8/8/8/4k3/8/4K3/8/8 w - - 0 1")  # K vs K
    outcome = board.outcome()
    assert outcome is not None
    assert outcome.termination == chess.Termination.INSUFFICIENT_MATERIAL
    assert _outcome_to_result(outcome) == ("draw", "insufficient_material")


def test_pgn_has_headers_and_moves():
    registry = GameRegistry()
    h1 = RandomBot(name="alice")
    h2 = RandomBot(name="bob")
    game = registry.create_game(
        white=Participant(bot=h1.info, is_house=True, house=h1),
        black=Participant(bot=h2.info, is_house=True, house=h2),
        time_control=TimeControl(base_seconds=180),
    )
    board = chess.Board()
    for uci in ("e2e4", "e7e5", "g1f3"):
        board.push_uci(uci)

    pgn = _render_pgn(game, board)
    assert '[White "alice"]' in pgn
    assert '[Black "bob"]' in pgn
    assert "1. e4 e5" in pgn
