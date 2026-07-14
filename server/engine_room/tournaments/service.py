"""Request-scoped tournament DB access (create + read views).

These run inside a REST request over the injected `get_async_session` seam (like
`bots/routes.py` / the spectator lobby). Enrollment and running the event are the
`TournamentManager`'s job (background, its own session factory) — this module is
just the human create endpoint and the anonymous read surface.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ids import new_id
from ..persistence.models import Bot, Tournament, TournamentEntry, TournamentGame


def _time_control(t: Tournament) -> dict:
    return {"base_seconds": t.base_seconds, "increment_seconds": t.increment_seconds}


async def create_tournament(
    session: AsyncSession,
    *,
    name: str,
    base_seconds: int,
    increment_seconds: int,
    target_size: int,
    created_by,
) -> Tournament:
    """Create a pending round-robin tournament owned by `created_by` (a user id)."""
    tournament = Tournament(
        id=new_id("tour"),
        name=name,
        format="round_robin",
        base_seconds=base_seconds,
        increment_seconds=increment_seconds,
        target_size=target_size,
        status="pending",
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
    )
    session.add(tournament)
    await session.commit()
    await session.refresh(tournament)
    return tournament


async def list_tournaments(session: AsyncSession) -> list[dict]:
    """Every tournament (newest first) with a light summary for the lobby list."""
    rows = (
        (await session.execute(select(Tournament).order_by(Tournament.created_at.desc())))
        .scalars()
        .all()
    )
    counts = dict(
        (
            await session.execute(
                select(TournamentEntry.tournament_id, func.count()).group_by(
                    TournamentEntry.tournament_id
                )
            )
        ).all()
    )
    return [
        {
            "id": t.id,
            "name": t.name,
            "format": t.format,
            "status": t.status,
            "time_control": _time_control(t),
            "target_size": t.target_size,
            "entry_count": int(counts.get(t.id, 0)),
            "created_at": t.created_at.isoformat(),
        }
        for t in rows
    ]


async def get_tournament(session: AsyncSession, tournament_id: str) -> dict | None:
    """Detail view: entries as standings (score desc, then seed) + the full
    schedule/results. `None` if there is no such tournament."""
    t = await session.get(Tournament, tournament_id)
    if t is None:
        return None

    entries = (
        (
            await session.execute(
                select(TournamentEntry).where(
                    TournamentEntry.tournament_id == tournament_id
                )
            )
        )
        .scalars()
        .all()
    )
    names: dict[str, str] = {}
    if entries:
        names = dict(
            (
                await session.execute(
                    select(Bot.id, Bot.name).where(
                        Bot.id.in_([e.bot_id for e in entries])
                    )
                )
            ).all()
        )
    standings = sorted(entries, key=lambda e: (-e.score, e.seed))

    games = (
        (
            await session.execute(
                select(TournamentGame)
                .where(TournamentGame.tournament_id == tournament_id)
                .order_by(TournamentGame.round, TournamentGame.id)
            )
        )
        .scalars()
        .all()
    )

    return {
        "id": t.id,
        "name": t.name,
        "format": t.format,
        "status": t.status,
        "time_control": _time_control(t),
        "target_size": t.target_size,
        # Owning user id (str) or None for a house/orphaned tournament. Surfaced so
        # the SPA can show the owner-only "Start" control to the creator only
        # (compared against GET /api/users/me). Read-only; no schema change.
        "created_by": str(t.created_by) if t.created_by is not None else None,
        "created_at": t.created_at.isoformat(),
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        "standings": [
            {
                "rank": i + 1,
                "bot_id": e.bot_id,
                "name": names.get(e.bot_id),
                "seed": e.seed,
                "score": e.score,
            }
            for i, e in enumerate(standings)
        ],
        "games": [
            {
                "round": g.round,
                "white_bot_id": g.white_bot_id,
                "black_bot_id": g.black_bot_id,
                "result": g.result,
                "game_id": g.game_id,
            }
            for g in games
        ],
    }
