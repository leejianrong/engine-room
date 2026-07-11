"""Public leaderboard read REST (KAN-51) — anonymous, read-only over the `bots`
table.

`GET /api/leaderboard` ranks bots by their Elo `rating` (descending) — the same
rating column the finalizer writes on every finished game (V5). No new data: this
is a pure projection of existing rows, so it degrades to "empty" rather than error
when there's nothing to show.

Only bots that have completed at least one rated game (`games_played > 0`) are
ranked — a leaderboard of never-played bots sitting at the 1200 default isn't a
ranking. Ties break on games_played (more games first) then name, so the order is
stable.

Uses the request-scoped `get_async_session` dependency (the REST DI seam, like
`bots/routes.py`); integration tests bind it to an ephemeral Postgres.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.db import get_async_session
from ..persistence.models import Bot

leaderboard_router = APIRouter()

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class LeaderboardEntry(BaseModel):
    rank: int
    bot_id: str
    name: str
    rating: int
    games_played: int
    is_house: bool


class LeaderboardResponse(BaseModel):
    entries: list[LeaderboardEntry]


@leaderboard_router.get("/api/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_async_session),
) -> LeaderboardResponse:
    stmt = (
        select(Bot)
        .where(Bot.games_played > 0)
        .order_by(Bot.rating.desc(), Bot.games_played.desc(), Bot.name.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    entries = [
        LeaderboardEntry(
            rank=i,
            bot_id=bot.id,
            name=bot.name,
            rating=bot.rating,
            games_played=bot.games_played,
            is_house=bot.is_house,
        )
        for i, bot in enumerate(rows, start=1)
    ]
    return LeaderboardResponse(entries=entries)
