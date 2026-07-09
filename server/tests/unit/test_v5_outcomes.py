"""V5 sub-step 3: worker terminals — resign, draw agreement, auto-draws, and the
D7 timeout-vs-insufficient-material rule. Driven by scripted in-process seats +
a pre-loaded control channel (no sockets, no DB). Rating stays stubbed here."""

import asyncio

import chess

from engine_room.game import worker as worker_mod
from engine_room.game.game import Participant
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import _timeout_result, run_game
from engine_room.protocol.messages import (
    BotInfo,
    DrawAccept,
    DrawOffer,
    Resign,
    TimeControl,
)
from engine_room.pubsub.inproc import InProcPubSub


class ScriptSeat:
    """A seat that plays a fixed list of UCI moves, then blocks forever (so the
    game ends only via a control/terminal, not by this seat running dry). Records
    the game_over it receives."""

    def __init__(self, color: str, moves=(), offer_on=None):
        self.color = color
        self._moves = list(moves)
        self._offer_on = offer_on  # ply index at which to piggyback offer_draw
        self._offer_draw = False
        self.over = None

    async def request_move(self, board, ply, last_move, clocks, applied=None,
                           opponent_draw_offer=False):
        if self._moves:
            uci = self._moves.pop(0)
            self._offer_draw = self._offer_on == ply
            return uci
        await asyncio.Event().wait()  # nothing left to do → block

    async def confirm_move(self, ply):
        return None

    async def game_over(self, result, termination, final_fen, pgn, **kw):
        self.over = {"result": result, "termination": termination}


def _game(white_seat, black_seat, fen=chess.STARTING_FEN):
    reg = GameRegistry()
    w = BotInfo(id="bot_w", name="w", rating=1200)
    b = BotInfo(id="bot_b", name="b", rating=1200)
    game = reg.create_game(
        white=Participant(bot=w, is_house=True),  # is_house avoids session/index
        black=Participant(bot=b, is_house=True),
        time_control=TimeControl(base_seconds=180),
    )
    game.initial_fen = fen
    # Attach our scripted seats + live state directly (bypass prepare_game).
    from engine_room.game.clock import Clock
    from engine_room.game.game import LiveState

    game.seats = {"white": white_seat, "black": black_seat}
    game.live = LiveState(board=chess.Board(fen), clock=Clock(game.white_ms, game.black_ms))
    game.live.__dict__  # noqa: B018 - ensure dataclass built
    return game


async def _play(game):
    # prepare_game is a no-op because game.live is already set.
    return await run_game(game, InProcPubSub())


# --- resign -------------------------------------------------------------------


def test_resign_makes_opponent_win():
    ws, bs = ScriptSeat("white"), ScriptSeat("black")
    game = _game(ws, bs)
    game.controls.put_nowait(("white", Resign(type="resign", game_id="g")))
    result, termination = asyncio.run(_play(game))
    assert (result, termination) == ("black_wins", "resignation")
    assert ws.over["result"] == "black_wins"
    assert bs.over["termination"] == "resignation"


# --- draw agreement -----------------------------------------------------------


def test_offer_then_accept_is_agreement():
    # White plays 1.e4 with a piggybacked offer; Black accepts on its turn.
    ws = ScriptSeat("white", moves=["e2e4"], offer_on=0)
    bs = ScriptSeat("black")
    game = _game(ws, bs)

    async def scenario():
        task = asyncio.ensure_future(_play(game))
        await asyncio.sleep(0.02)  # let White move + offer, Black get your_turn
        game.controls.put_nowait(("black", DrawAccept(type="draw_accept", game_id="g")))
        return await task

    result, termination = asyncio.run(scenario())
    assert (result, termination) == ("draw", "agreement")


def test_accept_without_offer_is_ignored_then_resign():
    # A draw_accept with no standing offer does nothing; a later resign still ends it.
    ws, bs = ScriptSeat("white"), ScriptSeat("black")
    game = _game(ws, bs)
    game.controls.put_nowait(("white", DrawAccept(type="draw_accept", game_id="g")))
    game.controls.put_nowait(("white", Resign(type="resign", game_id="g")))
    result, termination = asyncio.run(_play(game))
    assert (result, termination) == ("black_wins", "resignation")


def test_move_implicitly_declines_standing_offer():
    # Black offers (standalone) while White is to move; White then plays a move,
    # which declines. A subsequent White draw_accept has nothing to accept.
    ws = ScriptSeat("white", moves=["e2e4"])
    bs = ScriptSeat("black")
    game = _game(ws, bs)
    game.controls.put_nowait(("black", DrawOffer(type="draw_offer", game_id="g")))

    async def scenario():
        task = asyncio.ensure_future(_play(game))
        await asyncio.sleep(0.02)  # White consumes offer? no — White moves (declines)
        # After White's move the offer is cleared; a resign proves the game is live.
        game.controls.put_nowait(("white", Resign(type="resign", game_id="g")))
        return await task

    result, termination = asyncio.run(scenario())
    assert (result, termination) == ("black_wins", "resignation")
    assert game.live.pending_draw_offer is None


# --- auto-draws (D8) ----------------------------------------------------------


def test_fifty_move_auto_draw_via_claim():
    # A position at the 50-move threshold: after a non-pawn, non-capture move the
    # server auto-claims the draw (claim_draw=True, D8) — no bot claim needed.
    # Halfmove clock 99; one quiet move reaches 100 → fifty-move rule.
    fen = "7k/8/8/8/8/8/8/R6K w - - 99 80"
    ws = ScriptSeat("white", moves=["a1a2"])  # quiet rook move → clock hits 100
    bs = ScriptSeat("black")
    game = _game(ws, bs, fen=fen)
    result, termination = asyncio.run(_play(game))
    assert result == "draw"
    assert termination == "fifty_move"


# --- D7 timeout vs insufficient material --------------------------------------


def test_timeout_vs_insufficient_is_draw():
    # White (to move) flags but Black has only a king → draw, not black_wins (D7).
    board = chess.Board("7k/8/8/8/8/8/8/7K w - - 0 1")
    assert _timeout_result(board, chess.WHITE) == ("draw", "insufficient_material")


def test_timeout_with_mating_material_is_a_win():
    # Black has a rook → can mate → White flagging loses on time.
    board = chess.Board("7k/8/8/8/8/8/8/r6K w - - 0 1")
    assert _timeout_result(board, chess.WHITE) == ("black_wins", "timeout")


def test_module_helpers_exist():
    # Guard against accidental rename of the wired helpers.
    assert hasattr(worker_mod, "_timeout_result")
    assert worker_mod._other("white") == "black"
