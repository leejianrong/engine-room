"""Bot management REST API (auth-guarded, owner-scoped).

All routes require an authenticated human (current_active_user) and operate only
on that user's own bots (US 5–9). Key generation/rotation routes are added in
sub-step 4.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.deps import current_active_user
from ..persistence.db import get_async_session
from ..persistence.models import User
from . import service
from .schemas import BotCreate, BotRead, BotWithKey

router = APIRouter(prefix="/api/bots", tags=["bots"])


def _with_key(bot, plaintext: str) -> BotWithKey:
    """Build the shown-once response (BotRead fields + the plaintext key)."""
    return BotWithKey(**BotRead.model_validate(bot).model_dump(), api_key=plaintext)


@router.post("", response_model=BotWithKey, status_code=status.HTTP_201_CREATED)
async def create_bot(
    data: BotCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> BotWithKey:
    try:
        bot, plaintext = await service.create_bot(session, user.id, data)
    except service.BotCapReached:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"bot limit reached ({service.MAX_BOTS_PER_USER} per user)",
        )
    return _with_key(bot, plaintext)  # the key is shown exactly once (US 11)


@router.post("/{bot_id}/rotate-key", response_model=BotWithKey)
async def rotate_key(
    bot_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> BotWithKey:
    result = await service.rotate_key(session, user.id, bot_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bot not found")
    bot, plaintext = result
    return _with_key(bot, plaintext)  # old key is now invalid (ADR-0014)


@router.get("", response_model=list[BotRead])
async def list_bots(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[BotRead]:
    bots = await service.list_bots(session, user.id)
    return [BotRead.model_validate(b) for b in bots]


@router.get("/{bot_id}", response_model=BotRead)
async def get_bot(
    bot_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> BotRead:
    bot = await service.get_owned_bot(session, user.id, bot_id)
    if bot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bot not found")
    return BotRead.model_validate(bot)


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    if not await service.delete_bot(session, user.id, bot_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bot not found")
