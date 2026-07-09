"""Seed rows the app depends on at runtime — currently the house bot.

The house bot runs in-process but must exist as a `bots` row so that
`games.white_bot_id`/`black_bot_id` FKs resolve for house games (D-e/D-f). The
same canonical values are inserted by Alembic `0002` for real databases; this
helper seeds the create_all-based integration fixture / tests. Idempotent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..game.house_bots import (
    EPHRAIM_ID,
    EPHRAIM_NAME,
    EPHRAIM_RATING,
    JIAN_001_ID,
    JIAN_001_NAME,
    JIAN_001_RATING,
    JIAN_002_ID,
    JIAN_002_NAME,
    JIAN_002_RATING,
)
from .models import Bot

_HOUSE_BOTS = (
    # Ephemeral greeter (Kind-2): easy/random one-off opponent.
    (EPHRAIM_ID, EPHRAIM_NAME, EPHRAIM_RATING),
    # Permanent ambient bots (Kind-1): minimax lobby residents.
    (JIAN_001_ID, JIAN_001_NAME, JIAN_001_RATING),
    (JIAN_002_ID, JIAN_002_NAME, JIAN_002_RATING),
)


async def seed_house_bots(session) -> None:
    changed = False
    for bot_id, name, rating in _HOUSE_BOTS:
        if await session.get(Bot, bot_id) is not None:
            continue
        session.add(
            Bot(
                id=bot_id,
                owner_id=None,
                name=name,
                description="Built-in random-move house bot.",
                rating=rating,
                is_house=True,
                created_at=datetime.now(timezone.utc),
            )
        )
        changed = True
    if changed:
        await session.commit()
