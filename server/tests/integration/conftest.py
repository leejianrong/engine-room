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
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def _postgres_url():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        yield pg.get_connection_url()  # postgresql+psycopg://...


@pytest.fixture(scope="session")
def redis_url():
    """Ephemeral Redis for the KAN-62 cross-worker pub/sub test. Only tests that
    request it spin up the container (like `_postgres_url`)."""
    with RedisContainer("redis:7") as redis:
        host = redis.get_container_host_ip()
        port = redis.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def session_factory(_postgres_url):
    # REVISIT (WORKFLOW-ADOPTION Phase-D follow-up): build the schema by running
    # the real Alembic chain (`alembic upgrade head`) instead of `create_all`, so
    # every integration test also exercises the migrations. `test_v2_migrations`
    # covers the chain on a fresh container for now; env.py already accepts an
    # explicit `sqlalchemy.url`, so switching here is straightforward.
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
