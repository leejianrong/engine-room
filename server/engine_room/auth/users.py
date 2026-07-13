"""User database adapter + UserManager (FastAPI-Users)."""

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..persistence.db import get_async_session
from ..persistence.models import AccessToken, OAuthAccount, User


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncIterator[SQLAlchemyUserDatabase]:
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


async def get_access_token_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncIterator[SQLAlchemyAccessTokenDatabase]:
    """DB adapter for the revocable-session token table (KAN-72), backing the
    `DatabaseStrategy`. Mirrors `get_user_db`: request-scoped, so it rides the same
    overridable `get_async_session` seam tests bind to the testcontainer engine."""
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Governs user lifecycle. Token secrets reuse the single auth secret (D-l);
    password reset / email verification flows are dormant at MVP (OAuth-only)."""

    reset_password_token_secret = settings.auth_secret
    verification_token_secret = settings.auth_secret


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)
