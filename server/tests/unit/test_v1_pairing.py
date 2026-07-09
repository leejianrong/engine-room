"""V1 sub-step 3 checkpoint: a seek pairs the bot with a house bot (game_start)."""

from support.fake_client import FakeBotAuthenticator, connect

from engine_room.app import create_app
from engine_room.protocol.messages import BotInfo


def test_seek_pairs_with_house_bot():
    with connect(always_pair=True) as bot:
        bot.hello()
        ack = bot.seek(base_seconds=180)
        assert ack["type"] == "seek_ack"
        gs = bot.expect("game_start")

    assert gs["game_id"].startswith("game_")
    assert gs["your_color"] == "white"
    assert gs["opponent"]["name"] == "ephraim-bot"
    assert gs["opponent"]["rating"] == 1200
    assert gs["time_control"] == {"base_seconds": 180, "increment_seconds": 0}
    assert gs["clocks"] == {"white_ms": 180000, "black_ms": 180000}
    assert gs["initial_fen"].startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")
    assert gs["start_grace_ms"] == 10000


def test_five_plus_zero_pool_clocks():
    with connect(always_pair=True) as bot:
        bot.hello()
        bot.seek(base_seconds=300)
        gs = bot.expect("game_start")
    assert gs["clocks"] == {"white_ms": 300000, "black_ms": 300000}
    assert gs["time_control"]["base_seconds"] == 300


def test_each_seek_gets_a_distinct_game():
    # Two *different* bots on the same server each get their own game vs house.
    # (Distinct identities, so newest-wins doesn't evict the first — ADR-0016 A6.)
    authn = FakeBotAuthenticator(
        {
            "crbk_aaaa": BotInfo(id="bot_a", name="a", rating=1200),
            "crbk_bbbb": BotInfo(id="bot_b", name="b", rating=1200),
        }
    )
    app = create_app(bot_authenticator=authn, always_pair=True)
    with connect(app=app, token="crbk_aaaa") as bot1:
        bot1.hello()
        bot1.seek()
        g1 = bot1.expect("game_start")
        with connect(app=app, token="crbk_bbbb") as bot2:
            bot2.hello()
            bot2.seek()
            g2 = bot2.expect("game_start")
    assert g1["game_id"] != g2["game_id"]
