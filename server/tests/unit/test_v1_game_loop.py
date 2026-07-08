"""V1 sub-step 4 checkpoint: a full game completes to a terminal.

Primary WS test seam. Drives real python-chess play through the wire protocol.
"""

from support.fake_client import connect

_VALID_RESULTS = {"white_wins", "black_wins", "draw"}
_NATURAL_TERMINATIONS = {
    "checkmate",
    "stalemate",
    "insufficient_material",
    "fifty_move",
    "threefold_repetition",
}


def test_full_random_game_reaches_terminal():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        bot.expect("game_start")
        over = bot.play_out(seed=1234)

    assert over["type"] == "game_over"
    assert over["result"] in _VALID_RESULTS
    assert over["termination"] in _NATURAL_TERMINATIONS
    assert over["final_fen"]
    assert over["pgn"].startswith("[Event ")
    assert over["rating"] == {"before": 1200, "after": 1200}  # stubbed in V1


def test_first_your_turn_is_white_ply_zero():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        gs = bot.expect("game_start")
        yt = bot.expect("your_turn")
    assert yt["game_id"] == gs["game_id"]
    assert yt["ply"] == 0
    assert yt["your_color"] == "white"
    assert yt["last_move"] is None
    assert yt["fen"].startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")
    assert yt["clocks"] == {"white_ms": 180000, "black_ms": 180000}


def test_move_ack_echoes_correlation_id():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        bot.expect("game_start")
        yt = bot.expect("your_turn")
        import chess

        move = next(iter(chess.Board(yt["fen"]).legal_moves)).uci()
        bot.send({"type": "move", "game_id": yt["game_id"], "ply": 0, "uci": move, "id": "m0"})
        ack = bot.expect("move_ack")
    assert ack["ply"] == 0
    assert ack["accepted"] is True
    assert ack["id"] == "m0"


def test_flag_on_time_loses():
    # 1s clock; the bot never answers your_turn, so White flags on time.
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek(base_seconds=1)
        bot.expect("game_start")
        bot.expect("your_turn")  # ply 0, White — deliberately no reply
        over = bot.expect("game_over")
    assert over["result"] == "black_wins"
    assert over["termination"] == "timeout"


def test_your_turn_carries_opponents_last_move():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        bot.expect("game_start")
        yt0 = bot.expect("your_turn")  # ply 0, last_move None
        assert yt0["last_move"] is None

        import chess

        move = next(iter(chess.Board(yt0["fen"]).legal_moves)).uci()
        bot.send({"type": "move", "game_id": yt0["game_id"], "ply": 0, "uci": move})
        bot.expect("move_ack")
        yt2 = bot.expect("your_turn")  # ply 2 — carries the house bot's reply

    assert yt2["ply"] == 2
    assert yt2["your_color"] == "white"
    assert yt2["last_move"] is not None
    assert "uci" in yt2["last_move"] and "san" in yt2["last_move"]


def test_invalid_ply_is_reported_then_move_accepted():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        bot.expect("game_start")
        yt = bot.expect("your_turn")  # ply 0
        import chess

        legal = next(iter(chess.Board(yt["fen"]).legal_moves)).uci()
        # wrong ply -> INVALID_PLY, clock keeps running, still our turn
        bot.send({"type": "move", "game_id": yt["game_id"], "ply": 7, "uci": legal})
        err = bot.expect("error")
        assert err["code"] == "INVALID_PLY"
        # correct ply now accepted
        bot.send({"type": "move", "game_id": yt["game_id"], "ply": 0, "uci": legal})
        ack = bot.expect("move_ack")
    assert ack["ply"] == 0
