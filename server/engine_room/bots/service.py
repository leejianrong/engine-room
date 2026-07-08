"""Bot CRUD + the 5-per-user cap (ADR-0019 H1), owner-scoped.

Pure data-access functions over an AsyncSession — no FastAPI/HTTP here, so they
are unit-testable and reusable (the WS authenticator, sub-step 5, shares the same
persistence). Key generation/rotation is added in sub-step 4.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ids import new_id
from ..persistence.models import Bot
from . import MAX_BOTS_PER_USER
from .schemas import BotCreate


class BotCapReached(Exception):
    """Raised when a user already owns MAX_BOTS_PER_USER bots."""


async def count_owned(session: AsyncSession, owner_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count()).select_from(Bot).where(Bot.owner_id == owner_id)
    )


async def create_bot(session: AsyncSession, owner_id: uuid.UUID, data: BotCreate) -> Bot:
    if await count_owned(session, owner_id) >= MAX_BOTS_PER_USER:
        raise BotCapReached
    bot = Bot(
        id=new_id("bot"),
        owner_id=owner_id,
        name=data.name,
        description=data.description,
        created_at=datetime.now(timezone.utc),
    )
    session.add(bot)
    await session.commit()
    await session.refresh(bot)
    return bot


async def list_bots(session: AsyncSession, owner_id: uuid.UUID) -> list[Bot]:
    result = await session.execute(
        select(Bot).where(Bot.owner_id == owner_id).order_by(Bot.created_at)
    )
    return list(result.scalars().all())


async def get_owned_bot(
    session: AsyncSession, owner_id: uuid.UUID, bot_id: str
) -> Bot | None:
    """Fetch a bot only if it belongs to this owner (else None → 404)."""
    return await session.scalar(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == owner_id)
    )


async def delete_bot(session: AsyncSession, owner_id: uuid.UUID, bot_id: str) -> bool:
    bot = await get_owned_bot(session, owner_id, bot_id)
    if bot is None:
        return False
    await session.delete(bot)
    await session.commit()
    return True
