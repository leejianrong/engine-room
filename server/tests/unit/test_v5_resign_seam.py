"""V5 sub-step 3 (WS seam): a bot's `resign` control ends the game immediately.

Uses the always-pair-vs-house path so a lone seek yields an instant game; the
resign routes through the game-level control channel (not the move inbox)."""

from support.fake_client import connect


def test_resign_ends_game_opponent_wins():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        bot.expect("game_start")
        yt = bot.expect("your_turn")  # White (the seeker) is on move
        bot.send({"type": "resign", "game_id": yt["game_id"]})
        over = bot.expect("game_over")

    assert over["termination"] == "resignation"
    assert over["result"] == "black_wins"  # White resigned → house (Black) wins


def test_resign_routes_by_active_game_not_game_id():
    # The server routes a control by the bot's active game (like `move`), so a
    # resign is honored even without echoing the exact game_id.
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek()
        bot.expect("game_start")
        bot.expect("your_turn")
        bot.send({"type": "resign", "game_id": "whatever"})
        over = bot.expect("game_over")

    assert over["termination"] == "resignation"
    assert over["result"] == "black_wins"
