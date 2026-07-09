"""Seed rows the app depends on at runtime — currently the house bot.

The house bot runs in-process but must exist as a `bots` row so that
`games.white_bot_id`/`black_bot_id` FKs resolve for house games (D-e/D-f). The
same canonical values are inserted by Alembic `0002` for real databases; this
helper seeds the create_all-based integration fixture / tests. Idempotent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..game.house_bots import (
    HOUSE_RANDOM_2_ID,
    HOUSE_RANDOM_2_NAME,
    HOUSE_RANDOM_2_RATING,
    HOUSE_RANDOM_ID,
    HOUSE_RANDOM_NAME,
    HOUSE_RANDOM_RATING,
)
from .models import Bot

_HOUSE_BOTS = (
    (HOUSE_RANDOM_ID, HOUSE_RANDOM_NAME, HOUSE_RANDOM_RATING),
    # V6: the ambient house-vs-house opponent (ADR-0022 Kind-1).
    (HOUSE_RANDOM_2_ID, HOUSE_RANDOM_2_NAME, HOUSE_RANDOM_2_RATING),
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
