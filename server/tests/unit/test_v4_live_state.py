"""V4 sub-step 3 checkpoint: live-state snapshot, active-game index, move routing.

The reconnect payload (PROTOCOL §8), the bot_id→game index the endpoint uses to
find/route/rebind a seat, and the NO_ACTIVE_GAME guard for a move with no game.
"""

from support.fake_client import connect

from engine_room.game.game import Participant
from engine_room.game.house_bots import RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import prepare_game
from engine_room.protocol.messages import BotInfo, TimeControl


class FakeSession:
    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, message) -> None:
        self.sent.append(message)


def _two_real_game(reg: GameRegistry):
    a = BotInfo(id="bot_a", name="a", rating=1200)
    b = BotInfo(id="bot_b", name="b", rating=1200)
    game = reg.create_game(
        white=Participant(bot=a, session=FakeSession()),
        black=Participant(bot=b, session=FakeSession()),
        time_control=TimeControl(base_seconds=180),
    )
    return game


def test_resume_payload_matches_protocol_shape():
    reg = GameRegistry()
    game = _two_real_game(reg)
    prepare_game(game)
    # Simulate 1. e4 having been played — now Black to move at ply 1.
    live = game.live
    live.board.push_uci("e2e4")
    live.applied[0] = "e2e4"
    live.last_move = {"uci": "e2e4", "san": "e4"}
    live.ply = 1

    payload = game.resume_payload("bot_b")
    assert payload["game_id"] == game.id
    assert payload["your_color"] == "black"
    assert payload["to_move"] == "black"
    assert payload["ply"] == 1
    assert payload["last_move"] == {"uci": "e2e4", "san": "e4"}
    assert payload["clocks"] == {"white_ms": 180000, "black_ms": 180000}
    assert payload["opponent_draw_offer"] is False
    assert payload["fen"].split()[1] == "b"  # black to move


def test_resume_payload_none_for_unknown_bot():
    reg = GameRegistry()
    game = _two_real_game(reg)
    prepare_game(game)
    assert game.resume_payload("bot_not_in_game") is None


def test_active_index_binds_and_unbinds():
    reg = GameRegistry()
    game = _two_real_game(reg)

    reg.bind_active(game)
    assert reg.active_game_for("bot_a") is game
    assert reg.active_game_for("bot_b") is game

    reg.unbind_active(game)
    assert reg.active_game_for("bot_a") is None
    # Terminal is remembered so a missed game_over can be delivered on reconnect.
    assert reg.recent_terminal_for("bot_a") is game
    reg.clear_recent_terminal("bot_a")
    assert reg.recent_terminal_for("bot_a") is None


def test_house_participant_is_never_indexed():
    reg = GameRegistry()
    a = BotInfo(id="bot_a", name="a", rating=1200)
    house = RandomBot()
    game = reg.create_game(
        white=Participant(bot=a, session=FakeSession()),
        black=Participant(bot=house.info, is_house=True, house=house),
        time_control=TimeControl(base_seconds=180),
    )
    reg.bind_active(game)
    assert reg.active_game_for("bot_a") is game
    assert reg.active_game_for(house.info.id) is None  # no session → not indexed


def test_seat_for_finds_the_seat_by_bot():
    reg = GameRegistry()
    game = _two_real_game(reg)
    prepare_game(game)
    assert game.seat_for("bot_a").color == "white"
    assert game.seat_for("bot_b").color == "black"
    assert game.seat_for("nope") is None


def test_move_with_no_active_game_is_rejected():
    with connect() as bot:
        bot.hello()
        # A move before any game exists → NO_ACTIVE_GAME (§11), not a crash.
        bot.send({"type": "move", "game_id": "g", "ply": 0, "uci": "e2e4"})
        err = bot.expect("error")
    assert err["code"] == "NO_ACTIVE_GAME"
