"""V4 sub-step 2 checkpoint (WS seam): an illegal move forfeits the game.

Flips V1's report-and-ignore: an illegal/unparseable move on your turn is now an
instant forfeit → game_over{termination:"illegal_move"} (ADR-0016 B7).
"""

from support.fake_client import connect


def test_illegal_move_on_your_turn_forfeits():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        bot.expect("game_start")
        yt = bot.expect("your_turn")  # ply 0, White
        # e2e5 is not a legal opening move — illegal at the current ply.
        bot.send({"type": "move", "game_id": yt["game_id"], "ply": 0, "uci": "e2e5"})
        over = bot.expect("game_over")

    assert over["termination"] == "illegal_move"
    assert over["result"] == "black_wins"  # White (the seeker) forfeited


def test_unparseable_move_on_your_turn_forfeits():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        bot.expect("game_start")
        yt = bot.expect("your_turn")
        bot.send({"type": "move", "game_id": yt["game_id"], "ply": 0, "uci": "notauci"})
        over = bot.expect("game_over")

    assert over["termination"] == "illegal_move"
    assert over["result"] == "black_wins"
