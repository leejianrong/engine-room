"""The game loop (N5) — one asyncio task per active game.

Drives the your_turn/move/move_ack exchange under the server clock (N6),
applies moves with python-chess (the rules authority, ADR-0006), detects
natural terminals, and emits game_over. Finalization to Postgres (N8/N10) and
spectator fan-out (N7/N9) hook in at later sub-steps.
"""

from __future__ import annotations

import asyncio

import chess
import chess.pgn

from ..protocol.messages import Clocks
from .clock import Clock
from .game import Game
from .seat import HouseSeat, WsSeat

# python-chess termination -> ADR-0008 termination-reason vocabulary
_TERMINATION = {
    chess.Termination.CHECKMATE: "checkmate",
    chess.Termination.STALEMATE: "stalemate",
    chess.Termination.INSUFFICIENT_MATERIAL: "insufficient_material",
    chess.Termination.SEVENTYFIVE_MOVES: "fifty_move",
    chess.Termination.FIVEFOLD_REPETITION: "threefold_repetition",
    chess.Termination.FIFTY_MOVES: "fifty_move",
    chess.Termination.THREEFOLD_REPETITION: "threefold_repetition",
}


def _make_seat(participant, game_id: str, color: str):
    if participant.session is not None:
        return WsSeat(participant.session, game_id, color, participant.bot.rating)
    return HouseSeat(participant.house, game_id, color)


def _clocks(clock: Clock) -> Clocks:
    return Clocks(
        white_ms=clock.remaining_ms(chess.WHITE),
        black_ms=clock.remaining_ms(chess.BLACK),
    )


def _outcome_to_result(outcome: chess.Outcome) -> tuple[str, str]:
    if outcome.winner is True:
        result = "white_wins"
    elif outcome.winner is False:
        result = "black_wins"
    else:
        result = "draw"
    return result, _TERMINATION.get(outcome.termination, "aborted")


def _render_pgn(game: Game, board: chess.Board) -> str:
    pgn_game = chess.pgn.Game.from_board(board)  # sets Result from the outcome
    pgn_game.headers["Event"] = "Engine Room"
    pgn_game.headers["Site"] = "engine-room"
    pgn_game.headers["White"] = game.white.bot.name
    pgn_game.headers["Black"] = game.black.bot.name
    return str(pgn_game)


async def run_game(game: Game) -> tuple[str, str]:
    """Play the game to a terminal; return (result, termination)."""
    board = chess.Board(game.initial_fen)
    clock = Clock(game.white_ms, game.black_ms)
    inc_ms = game.time_control.increment_seconds * 1000
    seats = {
        chess.WHITE: _make_seat(game.white, game.id, "white"),
        chess.BLACK: _make_seat(game.black, game.id, "black"),
    }
    loop = asyncio.get_event_loop()

    game.state = "in_progress"
    ply = 0
    last_move = None
    result = termination = None

    while True:
        color = board.turn
        seat = seats[color]
        t0 = loop.time()
        try:
            uci = await asyncio.wait_for(
                seat.request_move(board=board, ply=ply, last_move=last_move, clocks=_clocks(clock)),
                timeout=clock.deadline_s(color),
            )
        except asyncio.TimeoutError:
            result = "black_wins" if color == chess.WHITE else "white_wins"
            termination = "timeout"
            break

        clock.charge(color, (loop.time() - t0) * 1000)

        move = chess.Move.from_uci(uci)  # request_move guarantees legality
        san = board.san(move)
        board.push(move)
        clock.credit_increment(color, inc_ms)  # 0 at MVP
        await seat.confirm_move(ply)
        last_move = {"uci": uci, "san": san}
        ply += 1

        outcome = board.outcome()  # automatic terminals (no claim); auto-draws are V5
        if outcome is not None:
            result, termination = _outcome_to_result(outcome)
            break

    game.state = "finished"
    final_fen = board.fen()
    pgn = _render_pgn(game, board)
    for seat in seats.values():
        await seat.game_over(result=result, termination=termination, final_fen=final_fen, pgn=pgn)
    return result, termination
