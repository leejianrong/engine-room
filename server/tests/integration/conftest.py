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
        # Truncate between tests so each starts from a clean slate (the container
        # is session-scoped and reused; the engine/schema are per-test).
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def app(session_factory):
    """A create_app() whose request-scoped DB session is bound to the ephemeral
    container (the REST/auth DI seam), mirroring how V1 injects the finalizer."""
    from engine_room.app import create_app
    from engine_room.persistence.db import get_async_session

    application = create_app()

    async def _override_session():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_async_session] = _override_session
    return application


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP client over the in-process ASGI app. httpx (not the sync
    TestClient) keeps requests on the same event loop as `session_factory`, so
    asyncpg connections aren't used across loops. https base_url so the OAuth
    CSRF cookie (Secure) is carried between requests."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def as_user(app):
    """Override `current_active_user` so a test acts as a given user without the
    OAuth round-trip (D-i). Returns a setter; pass a User (or any object with
    `.id`)."""
    from engine_room.auth.deps import current_active_user

    def _set(user):
        app.dependency_overrides[current_active_user] = lambda: user

    return _set


@pytest.fixture
def make_user(session_factory):
    """Insert a real User row (bots FK-reference it). Returns an async factory."""
    from engine_room.persistence.models import User

    async def _make(email: str = "dev@example.com"):
        async with session_factory() as session:
            user = User(
                email=email,
                hashed_password="not-used-oauth",
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _make
