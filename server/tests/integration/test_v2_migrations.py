"""Sub-step 1 checkpoint (integration): the Alembic migrations apply cleanly.

Runs the *real* migration chain (0001 → 0002 → …) against a fresh ephemeral
Postgres, closing the gap that the shared `session_factory` fixture leaves by
using `create_all` (see WORKFLOW-ADOPTION divergence / V2-plan O-3). Needs Docker.
"""

from alembic.config import Config
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer

from alembic import command


def test_migrations_apply_cleanly_on_fresh_db():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        sync_url = pg.get_connection_url()  # postgresql+psycopg://...
        async_url = sync_url.replace("+psycopg", "+asyncpg")

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", async_url)
        command.upgrade(cfg, "head")

        engine = create_engine(sync_url)
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

    # V1 + V2 identity tables all present after a clean upgrade to head.
    assert {"games", "user", "oauth_account", "bots"} <= tables
