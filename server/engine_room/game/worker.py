"""The game loop (N5) — one asyncio task per active game.

Drives the your_turn/move/move_ack exchange under the server clock (N6),
applies moves with python-chess (the rules authority, ADR-0006), detects
natural terminals, and emits game_over. Finalization to Postgres (N8/N10) and
spectator fan-out (N7/N9) hook in at later sub-steps.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

import chess
import chess.pgn

from ..channels import game_channel
from ..protocol.messages import Clocks
from .clock import Clock
from .game import Game
from .seat import HouseSeat, IllegalMoveForfeit, WsSeat

if TYPE_CHECKING:
    from ..pubsub.base import PubSub

# (game, result, termination, final_fen, pgn) -> None
Finalizer = Callable[[Game, str, str, str, str], Awaitable[None]]

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


def _make_seat(participant, game_id: str, color: str, house_delay: float = 0.0):
    if participant.session is not None:
        return WsSeat(participant.session, game_id, color, participant.bot.rating)
    return HouseSeat(participant.house, game_id, color, delay=house_delay)


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


async def run_game(
    game: Game,
    pubsub: "PubSub",
    finalizer: Optional[Finalizer] = None,
    house_move_delay: float = 0.0,
) -> tuple[str, str]:
    """Play the game to a terminal; return (result, termination).

    Publishes spectator events (game_start / move / game_over) to the game's
    channel via `pubsub` (N7) as the game unfolds. On the terminal, if a
    `finalizer` is provided, the durable record is written before the bots are
    notified (N8); when None, persistence is skipped. `house_move_delay` paces
    an in-process house seat's replies (dev watchability; default instant).
    """
    board = chess.Board(game.initial_fen)
    clock = Clock(game.white_ms, game.black_ms)
    inc_ms = game.time_control.increment_seconds * 1000
    seats = {
        chess.WHITE: _make_seat(game.white, game.id, "white", house_move_delay),
        chess.BLACK: _make_seat(game.black, game.id, "black", house_move_delay),
    }
    channel = game_channel(game.id)
    loop = asyncio.get_event_loop()

    game.state = "in_progress"
    await pubsub.publish(
        channel,
        {
            "type": "game_start",
            "game_id": game.id,
            "white": {"name": game.white.bot.name, "rating": game.white.bot.rating},
            "black": {"name": game.black.bot.name, "rating": game.black.bot.rating},
            "time_control": {
                "base_seconds": game.time_control.base_seconds,
                "increment_seconds": game.time_control.increment_seconds,
            },
            "initial_fen": game.initial_fen,
            "clocks": _clocks(clock).model_dump(),
        },
    )

    ply = 0
    last_move = None
    result = termination = None
    # ply -> uci already applied, so a blind resend at a past ply is re-acked
    # (never re-applied) by the seat (PROTOCOL §9). Moves to game.live in V4 s3.
    applied: dict[int, str] = {}

    while True:
        color = board.turn
        seat = seats[color]
        t0 = loop.time()
        try:
            uci = await asyncio.wait_for(
                seat.request_move(
                    board=board,
                    ply=ply,
                    last_move=last_move,
                    clocks=_clocks(clock),
                    applied=applied,
                ),
                timeout=clock.deadline_s(color),
            )
        except asyncio.TimeoutError:
            result = "black_wins" if color == chess.WHITE else "white_wins"
            termination = "timeout"
            break
        except IllegalMoveForfeit:
            # Illegal/unparseable move on your turn = instant forfeit (ADR-0016 B7).
            result = "black_wins" if color == chess.WHITE else "white_wins"
            termination = "illegal_move"
            break

        clock.charge(color, (loop.time() - t0) * 1000)

        move = chess.Move.from_uci(uci)  # request_move guarantees legality
        san = board.san(move)
        board.push(move)
        clock.credit_increment(color, inc_ms)  # 0 at MVP
        applied[ply] = uci
        await seat.confirm_move(ply)
        last_move = {"uci": uci, "san": san}
        await pubsub.publish(
            channel,
            {
                "type": "move",
                "ply": ply,
                "uci": uci,
                "san": san,
                "fen": board.fen(),
                "clocks": _clocks(clock).model_dump(),
                "to_move": "white" if board.turn == chess.WHITE else "black",
            },
        )
        ply += 1

        outcome = board.outcome()  # automatic terminals (no claim); auto-draws are V5
        if outcome is not None:
            result, termination = _outcome_to_result(outcome)
            break

    game.state = "finished"
    final_fen = board.fen()
    pgn = _render_pgn(game, board)
    if finalizer is not None:
        await finalizer(game, result, termination, final_fen, pgn)
    for seat in seats.values():
        await seat.game_over(result=result, termination=termination, final_fen=final_fen, pgn=pgn)
    await pubsub.publish(
        channel,
        {
            "type": "game_over",
            "game_id": game.id,
            "result": result,
            "termination": termination,
            "final_fen": final_fen,
        },
    )
    return result, termination
