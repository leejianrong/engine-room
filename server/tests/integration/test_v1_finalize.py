"""V1 finalization: a finished game writes one games row to Postgres.

Uses an ephemeral testcontainers Postgres (see conftest `session_factory`), so
it is self-contained — no hand-managed database, no skip.
"""

from engine_room.game.game import Participant
from engine_room.game.house_bots import RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import run_game
from engine_room.persistence.finalize import PostgresFinalizer
from engine_room.persistence.models import Game as GameRow
from engine_room.protocol.messages import TimeControl
from engine_room.pubsub.inproc import InProcPubSub


def _house_game(registry: GameRegistry):
    h1 = RandomBot(id="bot_h1", name="alice")
    h2 = RandomBot(id="bot_h2", name="bob")
    return registry.create_game(
        white=Participant(bot=h1.info, is_house=True, house=h1),
        black=Participant(bot=h2.info, is_house=True, house=h2),
        time_control=TimeControl(base_seconds=180),
    )


async def test_finalize_writes_one_games_row(session_factory):
    registry = GameRegistry()
    game = _house_game(registry)

    result, termination = await run_game(
        game, InProcPubSub(), PostgresFinalizer(session_factory)
    )

    async with session_factory() as session:
        row = await session.get(GameRow, game.id)

    assert row is not None
    assert row.result == result
    assert row.termination == termination
    assert row.white_name == "alice"
    assert row.black_name == "bob"
    assert row.base_seconds == 180
    assert row.increment_seconds == 0
    assert row.pgn.startswith("[Event ")
    assert row.final_fen
    assert row.created_at is not None
    assert row.finished_at is not None
