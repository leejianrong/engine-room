"""V1 sub-step 3 checkpoint: a seek pairs the bot with a house bot (game_start)."""

from fake_client import connect


def test_seek_pairs_with_house_bot():
    with connect() as bot:
        bot.hello()
        ack = bot.seek(base_seconds=180)
        assert ack["type"] == "seek_ack"
        gs = bot.expect("game_start")

    assert gs["game_id"].startswith("game_")
    assert gs["your_color"] == "white"
    assert gs["opponent"]["name"] == "house-random"
    assert gs["opponent"]["rating"] == 1200
    assert gs["time_control"] == {"base_seconds": 180, "increment_seconds": 0}
    assert gs["clocks"] == {"white_ms": 180000, "black_ms": 180000}
    assert gs["initial_fen"].startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")
    assert gs["start_grace_ms"] == 10000


def test_five_plus_zero_pool_clocks():
    with connect() as bot:
        bot.hello()
        bot.seek(base_seconds=300)
        gs = bot.expect("game_start")
    assert gs["clocks"] == {"white_ms": 300000, "black_ms": 300000}
    assert gs["time_control"]["base_seconds"] == 300


def test_each_seek_gets_a_distinct_game():
    with connect() as bot:
        bot.hello()
        bot.seek(cid="c1")
        g1 = bot.expect("game_start")
        bot.seek(cid="c2")
        g2 = bot.expect("game_start")
    assert g1["game_id"] != g2["game_id"]
