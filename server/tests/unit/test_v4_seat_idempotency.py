"""V4 sub-step 2 checkpoint: WsSeat ply-idempotency (§9) + illegal-move forfeit.

Drives WsSeat.request_move directly with a fake session so every §9 branch —
current / duplicate / stale / future — is deterministic (the WS seam can't
easily assert the *absence* of a frame for the stale-ignore case).
"""

import asyncio

import chess
import pytest

from engine_room.game.seat import IllegalMoveForfeit, WsSeat
from engine_room.protocol.messages import Clocks, Move


class FakeSession:
    def __init__(self) -> None:
        self.inbound: asyncio.Queue = asyncio.Queue()
        self.sent: list = []

    async def send(self, message) -> None:
        self.sent.append(message)


def _move(ply: int, uci: str, mid: str | None = None) -> Move:
    return Move(type="move", game_id="g", ply=ply, uci=uci, id=mid)


def _clocks() -> Clocks:
    return Clocks(white_ms=1000, black_ms=1000)


def _sent_types(sess: FakeSession) -> list[str]:
    return [m.type for m in sess.sent]


async def _seat_with(board: chess.Board) -> tuple[WsSeat, FakeSession]:
    sess = FakeSession()
    return WsSeat(sess, "g", "white", 1200), sess


async def test_current_ply_legal_move_is_returned():
    board = chess.Board()
    seat, sess = await _seat_with(board)
    legal = next(iter(board.legal_moves)).uci()
    await sess.inbound.put(_move(0, legal, "m0"))

    uci = await seat.request_move(board, 0, None, _clocks(), applied={})

    assert uci == legal
    assert "your_turn" in _sent_types(sess)  # a your_turn was emitted first


async def test_illegal_move_at_current_ply_forfeits():
    board = chess.Board()
    seat, sess = await _seat_with(board)
    await sess.inbound.put(_move(0, "e2e5"))  # not a legal opening move

    with pytest.raises(IllegalMoveForfeit) as exc:
        await seat.request_move(board, 0, None, _clocks(), applied={})
    assert exc.value.color == "white"


async def test_unparseable_move_at_current_ply_forfeits():
    board = chess.Board()
    seat, sess = await _seat_with(board)
    await sess.inbound.put(_move(0, "notauci"))

    with pytest.raises(IllegalMoveForfeit):
        await seat.request_move(board, 0, None, _clocks(), applied={})


async def test_duplicate_past_ply_is_reacked_not_reapplied():
    # Position after 1. e4 e5 — White to move at ply 2.
    board = chess.Board()
    board.push_uci("e2e4")
    board.push_uci("e7e5")
    seat, sess = await _seat_with(board)
    applied = {0: "e2e4", 1: "e7e5"}
    legal2 = next(iter(board.legal_moves)).uci()

    await sess.inbound.put(_move(0, "e2e4", "dup"))  # blind resend of ply 0
    await sess.inbound.put(_move(2, legal2, "m2"))  # the real ply-2 move

    uci = await seat.request_move(board, 2, None, _clocks(), applied=applied)

    assert uci == legal2
    # The duplicate was re-acked for ply 0 (not re-applied) before the real move.
    reacks = [m for m in sess.sent if m.type == "move_ack" and m.ply == 0]
    assert len(reacks) == 1 and reacks[0].id == "dup"


async def test_stale_conflicting_past_ply_is_ignored_not_penalized():
    board = chess.Board()
    board.push_uci("e2e4")
    board.push_uci("e7e5")
    seat, sess = await _seat_with(board)
    applied = {0: "e2e4", 1: "e7e5"}
    legal2 = next(iter(board.legal_moves)).uci()

    await sess.inbound.put(_move(0, "d2d4", "stale"))  # past ply, DIFFERENT uci
    await sess.inbound.put(_move(2, legal2, "m2"))

    uci = await seat.request_move(board, 2, None, _clocks(), applied=applied)

    assert uci == legal2
    # Stale conflicting resend: no re-ack, no error — silently ignored.
    assert "move_ack" not in _sent_types(sess)
    assert "error" not in _sent_types(sess)


async def test_future_ply_is_rejected_then_current_accepted():
    board = chess.Board()
    seat, sess = await _seat_with(board)
    legal = next(iter(board.legal_moves)).uci()

    await sess.inbound.put(_move(5, legal, "future"))  # ply > expected
    await sess.inbound.put(_move(0, legal, "m0"))

    uci = await seat.request_move(board, 0, None, _clocks(), applied={})

    assert uci == legal
    errors = [m for m in sess.sent if m.type == "error"]
    assert len(errors) == 1 and errors[0].code == "INVALID_PLY"
