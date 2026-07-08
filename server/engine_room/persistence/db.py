"""Async engine + session factory (SQLAlchemy 2.0, asyncpg driver)."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped DB session for the REST/auth layer (V2).

    Overridable in tests via `app.dependency_overrides[get_async_session]` so
    integration tests bind it to the testcontainer engine — the same DI seam
    philosophy as `create_app(finalizer=…)`, but request-scoped.
    """
    async with SessionLocal() as session:
        yield session
