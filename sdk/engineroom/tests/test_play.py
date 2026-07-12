"""SDK run-loop tests over the in-memory FakeServer (no network).

Sub-step 1 (happy path) + sub-step 2 (resilience: reconnect / resend / pong) +
sub-step 4 (resign / draw). Mirrors the layered test seams (ADR-0021): this is the
fast, infra-free layer; the packaged SDK is also run against the real server in the
live-uvicorn contract test (V7 sub-step 3).
"""

from __future__ import annotations

import chess
import pytest
from fakeserver import FakeServer

import engineroom
from engineroom import ACCEPT_DRAW, RESIGN, Bot, GreedyBot, RandomBot


def _bot(server: FakeServer, cls=RandomBot, **kw) -> Bot:
    return cls(key="crbk_test", connect=server.connect, **kw)


# --------------------------------------------------------------- happy path
async def test_random_bot_plays_a_full_game():
    server = FakeServer(max_plies=8)
    overs: list = []
    starts: list = []

    class Watched(RandomBot):
        def on_game_start(self, info):
            starts.append(info)

        def on_game_over(self, result):
            overs.append(result)

    bot = Watched(key="crbk_test", connect=server.connect, seed=1)
    await bot._run(loop=False)

    assert len(starts) == 1 and starts[0].game_id == "game_fake"
    assert starts[0].your_color == "white"
    assert len(overs) == 1
    assert overs[0].result in ("draw", "white_wins", "black_wins")
    assert overs[0].rating == {"before": 1200, "after": 1208}
    # Every move the bot sent was at an even (White) ply, in order, and legal.
    plies = [p for p, _ in server.moves_received]
    assert plies == sorted(plies)
    assert all(p % 2 == 0 for p in plies)
    assert server.bot_move_count >= 1


async def test_move_returned_as_uci_string_is_accepted():
    server = FakeServer(max_plies=4)

    class StringBot(Bot):
        def choose_move(self, board):
            return next(iter(board.legal_moves)).uci()  # a UCI str, not a Move

    await StringBot(key="crbk_test", connect=server.connect)._run(loop=False)
    assert server.bot_move_count >= 1


async def test_missing_key_raises_config_error():
    server = FakeServer()
    bot = RandomBot(key=None, url="ws://x", connect=server.connect)
    with pytest.raises(engineroom.ConfigError):
        await bot._run(loop=False)


# --------------------------------------------------------------- resilience
async def test_heartbeat_ping_is_ponged_transparently():
    # ping_before_turn makes the server ping before every your_turn; the game
    # completing at all proves the SDK ponged (else liveness would stall here).
    server = FakeServer(max_plies=6, ping_before_turn=True)
    await _bot(server, seed=2)._run(loop=False)
    assert server.bot_move_count >= 1


async def test_dropped_move_is_resent_idempotently():
    # The server silently drops the bot's first move; the SDK must resend the
    # identical frame after its ack timeout (§9) so the game proceeds.
    server = FakeServer(max_plies=6, withhold_moves=1)
    bot = _bot(server, seed=3)
    bot._ack_timeout = 0.05  # keep the test fast
    await bot._run(loop=False)
    # The first frame was sent, dropped, then resent at the same ply.
    assert server.moves_received[0][0] == server.moves_received[1][0] == 0
    assert server.bot_move_count >= 1


async def test_mid_game_drop_reconnects_and_resumes():
    server = FakeServer(max_plies=12, drop_after_bot_moves=2)
    bot = _bot(server, seed=4)
    await bot._run(loop=False)
    assert server.connections >= 2  # reconnected at least once
    assert server.bot_move_count >= 3  # finished the game after resuming


# ------------------------------------------------------------- resign / draw
async def test_resign_sentinel_ends_the_game():
    server = FakeServer(max_plies=100)

    class Resigner(Bot):
        def choose_move(self, board):
            return RESIGN

    overs: list = []

    class Watched(Resigner):
        def on_game_over(self, result):
            overs.append(result)

    await Watched(key="crbk_test", connect=server.connect)._run(loop=False)
    assert server.resigned is True
    assert overs[0].termination == "resignation"


async def test_accept_draw_sentinel_agrees_to_a_draw():
    server = FakeServer(max_plies=100)

    class Accepter(Bot):
        def choose_move(self, board):
            return ACCEPT_DRAW

    await Accepter(key="crbk_test", connect=server.connect)._run(loop=False)
    assert server.draw_agreed is True


# --------------------------------------------------------------- codec check
def test_reference_bots_pick_legal_moves():
    board = chess.Board()
    assert RandomBot(key="k").choose_move(board) in board.legal_moves
    greedy = GreedyBot(key="k").choose_move(board)
    assert chess.Move.from_uci(greedy) in board.legal_moves
    uci = engineroom.MinimaxBot(key="k").choose_move(board)
    assert chess.Move.from_uci(uci) in board.legal_moves


def test_greedy_bot_grabs_the_hanging_queen():
    # White rook on g1, White king on h1, a lone hanging Black queen on a1.
    # The one-ply material grab is Rxa1; a greedy bot must take it.
    board = chess.Board("7k/8/8/8/8/8/8/q5RK w - - 0 1")
    uci = GreedyBot(key="k", seed=0).choose_move(board)
    move = chess.Move.from_uci(uci)
    assert move in board.legal_moves
    assert move == chess.Move.from_uci("g1a1")
