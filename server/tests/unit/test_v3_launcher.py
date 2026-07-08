"""V3 sub-step 3: game_start_for builds each seat's perspective correctly.

(The full launch → game_start → play path is exercised end-to-end by the V1
pairing/game-loop tests, which now run through GameLauncher.)"""

from datetime import datetime, timezone

from engine_room.game.game import Game, Participant
from engine_room.matchmaking.launcher import game_start_for
from engine_room.protocol.messages import BotInfo, TimeControl


def _game():
    tc = TimeControl(base_seconds=180)
    return Game(
        id="game_x",
        white=Participant(bot=BotInfo(id="bot_w", name="whitey", rating=1300)),
        black=Participant(bot=BotInfo(id="bot_b", name="blacky", rating=1250)),
        time_control=tc,
        initial_fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        white_ms=180000,
        black_ms=180000,
        created_at=datetime.now(timezone.utc),
    )


def test_white_perspective_sees_black_as_opponent():
    gs = game_start_for(_game(), "white")
    assert gs.your_color == "white"
    assert gs.opponent.id == "bot_b"
    assert gs.clocks.white_ms == 180000


def test_black_perspective_sees_white_as_opponent():
    gs = game_start_for(_game(), "black")
    assert gs.your_color == "black"
    assert gs.opponent.id == "bot_w"


def test_opponent_serialization_omits_owner_id():
    gs = game_start_for(_game(), "white")
    assert "owner_id" not in gs.model_dump()["opponent"]
