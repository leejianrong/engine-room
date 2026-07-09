"""The game loop (N5) — one asyncio task per active game.

Drives the your_turn/move/move_ack exchange under the server clock (N6),
applies moves with python-chess (the rules authority, ADR-0006), detects
natural terminals, and emits game_over. Finalization to Postgres (N8/N10) and
spectator fan-out (N7/N9) hook in at later sub-steps.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

import chess
import chess.pgn

from ..channels import game_channel
from ..protocol.messages import Clocks, DrawAccept, DrawOffer, Resign
from .clock import Clock
from .game import Game, LiveState
from .seat import HouseSeat, IllegalMoveForfeit, WsSeat

_COLOR_NAME = {chess.WHITE: "white", chess.BLACK: "black"}


def _other(color: str) -> str:
    return "black" if color == "white" else "white"

if TYPE_CHECKING:
    from ..persistence.finalize import FinalizeResult
    from ..pubsub.base import PubSub
    from .registry import GameRegistry

# (game, result, termination, final_fen, pgn) -> FinalizeResult | None
# The result carries each side's persisted Elo (before, after) so game_over can
# report the same numbers that were written (ADR-0025 #5); None on ABORTED or the
# DB-free path (then the loop stubs the rating).
Finalizer = Callable[[Game, str, str, str, str], Awaitable["Optional[FinalizeResult]"]]

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


def prepare_game(game: Game, house_move_delay: float = 0.0) -> None:
    """Attach seats + live state to a game so a reconnect that races the first
    move already finds a bound seat (V4 D-i). Idempotent — the launcher calls it
    before `game_start`; `run_game` calls it too so a direct-call (test/house)
    path still works. A no-op once `game.live` is set."""
    if game.live is not None:
        return
    game.seats = {
        "white": _make_seat(game.white, game.id, "white", house_move_delay),
        "black": _make_seat(game.black, game.id, "black", house_move_delay),
    }
    game.live = LiveState(
        board=chess.Board(game.initial_fen),
        clock=Clock(game.white_ms, game.black_ms),
    )


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


def _timeout_result(board: chess.Board, flagged: bool) -> tuple[str, str]:
    """The result when `flagged` (a chess color) runs out of clock. Normally the
    opponent wins on time, but if the opponent has insufficient mating material
    the game is a DRAW, not a win (ADR-0016 D7; python-chess decides)."""
    winner = not flagged
    if board.has_insufficient_material(winner):
        return "draw", "insufficient_material"
    return ("black_wins" if flagged == chess.WHITE else "white_wins"), "timeout"


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
    registry: Optional["GameRegistry"] = None,
) -> tuple[str, str]:
    """Play the game to a terminal; return (result, termination).

    Publishes spectator events (game_start / move / game_over) to the game's
    channel via `pubsub` (N7) as the game unfolds. On the terminal, if a
    `finalizer` is provided, the durable record is written before the bots are
    notified (N8); when None, persistence is skipped. `house_move_delay` paces
    an in-process house seat's replies (dev watchability; default instant).

    V4: operates on `game.live` (board/clock/ply/last-move + applied history) so a
    reconnect can read a consistent snapshot; if `registry` is given, the game is
    unbound from the active-game index at terminal.
    """
    prepare_game(game, house_move_delay)
    live = game.live
    board = live.board
    clock = live.clock
    seats = {chess.WHITE: game.seats["white"], chess.BLACK: game.seats["black"]}
    inc_ms = game.time_control.increment_seconds * 1000
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

    result = termination = None
    # Wakes the loop when both seats are abandoned → ABORTED (I7). Kept across
    # turns; cancelled after the loop.
    abort_wait = asyncio.ensure_future(game.abort.wait())

    while result is None:
        color = board.turn
        name = _COLOR_NAME[color]
        seat = seats[color]
        ply = live.ply
        t0 = loop.time()
        deadline = clock.deadline_s(color)
        move_task = asyncio.ensure_future(
            seat.request_move(
                board=board,
                ply=ply,
                last_move=live.last_move,
                clocks=_clocks(clock),
                applied=live.applied,
                # Surface a standing offer from the opponent (D6).
                opponent_draw_offer=(
                    live.pending_draw_offer is not None
                    and live.pending_draw_offer != name
                ),
            )
        )
        # Inner loop: resolve THIS turn. `move_task`/`abort_wait` persist across
        # control drains; only `ctrl_task` is recreated each pass (V5 D-a).
        uci = None
        while result is None and uci is None:
            ctrl_task = asyncio.ensure_future(game.controls.get())
            done, _ = await asyncio.wait(
                {move_task, abort_wait, ctrl_task},
                timeout=max(0.0, deadline - (loop.time() - t0)),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if ctrl_task not in done:
                ctrl_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await ctrl_task

            if abort_wait in done:
                move_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await move_task
                result, termination = "aborted", "aborted"  # (I7)
            elif ctrl_task in done:
                c_color, c_msg = ctrl_task.result()
                if isinstance(c_msg, Resign):
                    # Resign is unconditional — the sender loses (ADR-0008).
                    result = "black_wins" if c_color == "white" else "white_wins"
                    termination = "resignation"
                elif isinstance(c_msg, DrawAccept):
                    # Valid only against a standing offer from the OTHER side (D6).
                    if live.pending_draw_offer == _other(c_color):
                        result, termination = "draw", "agreement"
                    # else: nothing to accept → ignore, keep waiting.
                elif isinstance(c_msg, DrawOffer):
                    # Standing until the recipient moves; surfaced on their next
                    # your_turn (D6). No your_turn re-send mid-turn (O-1).
                    live.pending_draw_offer = c_color
                if result is not None:
                    move_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await move_task
            elif move_task in done:
                try:
                    uci = move_task.result()
                except IllegalMoveForfeit:
                    # Illegal/unparseable move = instant forfeit (ADR-0016 B7).
                    result = "black_wins" if color == chess.WHITE else "white_wins"
                    termination = "illegal_move"
            else:
                # Deadline: neither a move, control, nor abort → flag (D7 applies).
                move_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await move_task
                result, termination = _timeout_result(board, color)

        if result is not None:
            break

        clock.charge(color, (loop.time() - t0) * 1000)

        move = chess.Move.from_uci(uci)  # request_move guarantees legality
        san = board.san(move)
        board.push(move)
        clock.credit_increment(color, inc_ms)  # 0 at MVP
        live.applied[ply] = uci
        # Draw-offer lifecycle (D6): a move by this side implicitly declines a
        # standing offer against it; a piggybacked offer then becomes the new one.
        if live.pending_draw_offer == _other(name):
            live.pending_draw_offer = None
        if getattr(seat, "_offer_draw", False):
            live.pending_draw_offer = name
        await seat.confirm_move(ply)
        live.last_move = {"uci": uci, "san": san}
        fen = board.fen()
        # Append to the live move history — the catch-up snapshot + replay source
        # (V6 D-c). Same four fields as the `move` event below, so snapshot-moves
        # + the live tail form one uniform client-side list.
        live.moves.append({"ply": ply, "uci": uci, "san": san, "fen": fen})
        await pubsub.publish(
            channel,
            {
                "type": "move",
                "ply": ply,
                "uci": uci,
                "san": san,
                "fen": fen,
                "clocks": _clocks(clock).model_dump(),
                "to_move": "white" if board.turn == chess.WHITE else "black",
            },
        )
        live.ply = ply + 1

        # Auto-draws with no claim protocol (ADR-0016 D8): claim_draw=True makes
        # the server auto-claim threefold/fifty-move as well as the always-on
        # stalemate/insufficient/fivefold/75-move terminals.
        outcome = board.outcome(claim_draw=True)
        if outcome is not None:
            result, termination = _outcome_to_result(outcome)
            break

    abort_wait.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await abort_wait

    game.state = "aborted" if termination == "aborted" else "finished"
    final_fen = board.fen()
    pgn = _render_pgn(game, board)
    # Stash the terminal so a bot that missed game_over while away can be told on
    # reconnect (D-vi); unbind from the active-game index.
    game.result, game.termination, game.final_fen, game.pgn = (
        result,
        termination,
        final_fen,
        pgn,
    )
    outcome = None
    if finalizer is not None:
        outcome = await finalizer(game, result, termination, final_fen, pgn)
    for seat in seats.values():
        before = after = None
        if outcome is not None:
            before, after = outcome.white if seat.color == "white" else outcome.black
        await seat.game_over(
            result=result,
            termination=termination,
            final_fen=final_fen,
            pgn=pgn,
            rating_before=before,
            rating_after=after,
        )
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
    if registry is not None:
        registry.unbind_active(game)
    return result, termination
