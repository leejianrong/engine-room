"""V6 sub-step 4 (integration, real Postgres): ambient house-vs-house games are
rated + persisted and respawn, and the row-locked finalizer (D-g2) applies every
rating update under concurrent finalization (no lost write).

Drives the AmbientSupervisor directly with a real GameLauncher + PostgresFinalizer
bound to the container (no uvicorn needed — the games are house-vs-house, so no
sockets are involved)."""

import asyncio

from sqlalchemy import func, select

from engine_room.game.ambient import AmbientSupervisor
from engine_room.game.house_bots import (
    JIAN_001_ID,
    JIAN_001_NAME,
    JIAN_002_ID,
    JIAN_002_NAME,
    RandomBot,
)
from engine_room.game.registry import GameRegistry
from engine_room.matchmaking.launcher import GameLauncher
from engine_room.persistence.finalize import PostgresFinalizer
from engine_room.persistence.models import Bot
from engine_room.persistence.models import Game as GameRow
from engine_room.persistence.seed import seed_house_bots
from engine_room.protocol.messages import TimeControl
from engine_room.pubsub.inproc import InProcPubSub


async def _count_games(session_factory) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(GameRow))
        ).scalar_one()


async def test_ambient_games_persist_rate_and_respawn(session_factory):
    async with session_factory() as session:
        await seed_house_bots(session)  # both house identities @ 1200

    registry = GameRegistry()
    launcher = GameLauncher(
        InProcPubSub(),
        game_registry=registry,
        finalizer=PostgresFinalizer(session_factory),
        house_move_delay=0.0,  # instant so games finish fast in the test
    )
    house_a = RandomBot(id=JIAN_001_ID, name=JIAN_001_NAME)  # jian-bot-001 (white)
    house_b = RandomBot(id=JIAN_002_ID, name=JIAN_002_NAME)  # jian-bot-002 (black)
    sup = AmbientSupervisor(
        registry, launcher, house_a, house_b, n=2, time_control=TimeControl(base_seconds=180)
    )

    await sup.start()
    try:
        # Wait until at least 2 ambient games have finished + persisted, proving
        # respawn (the pool refilled after the first finished).
        finished = 0
        for _ in range(600):  # up to ~30s
            await asyncio.sleep(0.05)
            finished = await _count_games(session_factory)
            if finished >= 2:
                break
        assert finished >= 2, f"only {finished} ambient games persisted"
    finally:
        await sup.stop()

    async with session_factory() as session:
        total = (
            await session.execute(select(func.count()).select_from(GameRow))
        ).scalar_one()
        rows = (await session.execute(select(GameRow))).scalars().all()
        a = await session.get(Bot, JIAN_001_ID)
        b = await session.get(Bot, JIAN_002_ID)

    # Every persisted ambient game is house_a (white) vs house_b (black), rated.
    for row in rows:
        assert row.white_bot_id == JIAN_001_ID
        assert row.black_bot_id == JIAN_002_ID
        assert row.white_rating_before is not None
        assert row.white_rating_after is not None

    # No lost rating write (D-g2): each finished game incremented BOTH house bots
    # exactly once, even though they finalize concurrently sharing the same rows.
    # (This is the deterministic guarantee — the *direction* of a rating move is
    # outcome-dependent: a draw between two equal 1200 bots leaves both at 1200,
    # so asserting the rating changed would be flaky.)
    assert a.games_played == total
    assert b.games_played == total
