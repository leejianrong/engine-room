"""Tournament REST (KAN-56).

- `POST /api/tournaments` — create a round-robin tournament (authenticated human,
  owner-scoped via `current_active_user`, like `bots/routes.py`).
- `POST /api/tournaments/{id}/start` — explicitly start a pending tournament
  (owner-only). A tournament also auto-starts once it reaches `target_size`.
- `GET  /api/tournaments` — list (anonymous, read-only, like the spectator lobby).
- `GET  /api/tournaments/{id}` — detail: standings (score desc) + schedule/results.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.deps import current_active_user
from ..persistence.db import get_async_session
from ..persistence.models import Tournament, User
from ..protocol.messages import TimeControl
from . import service

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])


class TournamentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    time_control: TimeControl
    target_size: int = Field(ge=2, le=64)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tournament(
    data: TournamentCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    tournament = await service.create_tournament(
        session,
        name=data.name,
        base_seconds=data.time_control.base_seconds,
        increment_seconds=data.time_control.increment_seconds,
        target_size=data.target_size,
        created_by=user.id,
    )
    detail = await service.get_tournament(session, tournament.id)
    assert detail is not None  # just created
    return detail


@router.post("/{tournament_id}/start")
async def start_tournament(
    tournament_id: str,
    request: Request,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    t = await session.get(Tournament, tournament_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such tournament")
    if t.created_by is not None and t.created_by != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your tournament")
    started = await request.app.state.tournament_manager.start_tournament(tournament_id)
    if not started:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tournament is not pending",
        )
    return {"status": "running"}


@router.get("")
async def list_tournaments(
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    return {"tournaments": await service.list_tournaments(session)}


@router.get("/{tournament_id}")
async def get_tournament(
    tournament_id: str,
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    detail = await service.get_tournament(session, tournament_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such tournament")
    return detail
