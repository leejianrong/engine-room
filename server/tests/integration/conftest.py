"""Integration fixtures: an ephemeral Postgres via testcontainers.

Only tests that request `session_factory` spin up the database, so the other
integration tests (e.g. the real-server SSE test) stay Docker-free. The
container's readiness probe uses the sync `psycopg` driver; the app engine uses
`asyncpg`.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def _postgres_url():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        yield pg.get_connection_url()  # postgresql+psycopg://...


@pytest_asyncio.fixture
async def session_factory(_postgres_url):
    from engine_room.persistence.models import Base

    async_url = _postgres_url.replace("+psycopg", "+asyncpg")
    engine = create_async_engine(async_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
