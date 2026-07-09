"""Finalization: a finished game writes one games row to Postgres.

V1 wrote result/termination/PGN; V2 also writes the real bot FKs (ADR-0009) and
keeps the *_name snapshot (D-f). Uses the ephemeral testcontainers Postgres.
"""

from datetime import datetime, timezone

from engine_room.game.game import Participant
from engine_room.game.house_bots import EPHRAIM_ID, RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import run_game
from engine_room.persistence.finalize import PostgresFinalizer
from engine_room.persistence.models import Bot
from engine_room.persistence.models import Game as GameRow
from engine_room.persistence.seed import seed_house_bots
from engine_room.protocol.messages import TimeControl
from engine_room.pubsub.inproc import InProcPubSub


async def _seed_bots(session_factory):
    """The bots the game references must exist for the FKs to resolve."""
    async with session_factory() as session:
        await seed_house_bots(session)  # bot_ephraim (black)
        session.add(
            Bot(
                id="bot_user1",
                name="alice",
                description="",
                rating=1200,
                is_house=True,  # in-process mover for the test; identity is real
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


def _house_game(registry: GameRegistry):
    white = RandomBot(id="bot_user1", name="alice")
    black = RandomBot()  # canonical house bot: bot_ephraim / ephraim-bot
    return registry.create_game(
        white=Participant(bot=white.info, is_house=True, house=white),
        black=Participant(bot=black.info, is_house=True, house=black),
        time_control=TimeControl(base_seconds=180),
    )


async def test_finalize_writes_one_games_row_with_bot_fks(session_factory):
    await _seed_bots(session_factory)
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
    # V2 FKs to the real bots + the kept name snapshot.
    assert row.white_bot_id == "bot_user1"
    assert row.black_bot_id == EPHRAIM_ID
    assert row.white_name == "alice"
    assert row.black_name == "ephraim-bot"
    assert row.base_seconds == 180
    assert row.increment_seconds == 0
    assert row.pgn.startswith("[Event ")
    assert row.final_fen
    assert row.created_at is not None
    assert row.finished_at is not None


async def test_deleting_a_bot_nulls_the_game_fk_but_keeps_history(session_factory):
    await _seed_bots(session_factory)
    registry = GameRegistry()
    game = _house_game(registry)
    await run_game(game, InProcPubSub(), PostgresFinalizer(session_factory))

    # Delete the white bot (US 9); ON DELETE SET NULL preserves the game row.
    async with session_factory() as session:
        await session.delete(await session.get(Bot, "bot_user1"))
        await session.commit()

    async with session_factory() as session:
        row = await session.get(GameRow, game.id)

    assert row is not None  # history survives
    assert row.white_bot_id is None  # FK nulled by the delete
    assert row.white_name == "alice"  # snapshot still readable
    assert row.black_bot_id == EPHRAIM_ID  # the other side is untouched
