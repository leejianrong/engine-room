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
            insp = inspect(engine)
            tables = set(insp.get_table_names())
            games_cols = {c["name"] for c in insp.get_columns("games")}
            with engine.connect() as conn:
                house = conn.exec_driver_sql(
                    "SELECT id, is_house FROM bots WHERE id = 'bot_house_random'"
                ).first()
        finally:
            engine.dispose()

    # V1 + V2 identity tables all present after a clean upgrade to head, plus the
    # KAN-72 revocable-session token table (migration 0006).
    assert {"games", "user", "oauth_account", "bots", "accesstoken"} <= tables
    # games gained the bot FKs (D-f) and the house bot is seeded (ADR-0022).
    assert {"white_bot_id", "black_bot_id"} <= games_cols
    assert house is not None and house[1] is True
