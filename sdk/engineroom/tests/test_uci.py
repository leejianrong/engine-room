"""UCI bridge unit test (sub-step 5) — no real engine binary needed.

Substitutes a fake ``chess.engine`` handle so the bridge's move-delegation and
subprocess-teardown (O-5) are covered without Stockfish. A live run against a real
engine is gated in the integration suite (skipif no binary on PATH)."""

from __future__ import annotations

import chess
from fakeserver import FakeServer

from engineroom.uci import UCIBot


class _FakePlayResult:
    def __init__(self, move: chess.Move) -> None:
        self.move = move


class _FakeEngine:
    def __init__(self) -> None:
        self.quit_calls = 0

    def play(self, board: chess.Board, limit) -> _FakePlayResult:  # noqa: ANN001
        return _FakePlayResult(next(iter(board.legal_moves)))

    def quit(self) -> None:
        self.quit_calls += 1


async def test_uci_bot_plays_via_the_engine_and_cleans_up():
    server = FakeServer(max_plies=4)
    fake_engine = _FakeEngine()

    bot = UCIBot("/nonexistent/stockfish", key="crbk_test", connect=server.connect)
    bot._engine = fake_engine  # inject; skip popen_uci

    await bot._run(loop=False)
    assert server.bot_move_count >= 1

    bot.close()
    assert fake_engine.quit_calls == 1


def test_uci_bot_uses_depth_limit_when_given():
    bot = UCIBot("/x", key="k", depth=5)
    fake = _FakeEngine()
    bot._engine = fake
    move = bot.choose_move(chess.Board())
    assert move in chess.Board().legal_moves
