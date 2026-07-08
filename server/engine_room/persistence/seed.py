"""Seed rows the app depends on at runtime — currently the house bot.

The house bot runs in-process but must exist as a `bots` row so that
`games.white_bot_id`/`black_bot_id` FKs resolve for house games (D-e/D-f). The
same canonical values are inserted by Alembic `0002` for real databases; this
helper seeds the create_all-based integration fixture / tests. Idempotent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..game.house_bots import HOUSE_RANDOM_ID, HOUSE_RANDOM_NAME, HOUSE_RANDOM_RATING
from .models import Bot


async def seed_house_bots(session) -> None:
    if await session.get(Bot, HOUSE_RANDOM_ID) is not None:
        return
    session.add(
        Bot(
            id=HOUSE_RANDOM_ID,
            owner_id=None,
            name=HOUSE_RANDOM_NAME,
            description="Built-in random-move house bot.",
            rating=HOUSE_RANDOM_RATING,
            is_house=True,
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
