"""DB URL normalization (deploy hardening): coerce Postgres URLs to the async
driver + translate libpq SSL params, so a raw Neon/Heroku connection string
works and can't reproduce the psycopg2 ModuleNotFoundError. Pure function."""

import logging

from engine_room.config import _normalize_pg_url


def test_raw_neon_url_is_coerced():
    out = _normalize_pg_url(
        "postgresql://u:pw@ep-x.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert out == "postgresql+asyncpg://u:pw@ep-x.neon.tech/db?ssl=require"


def test_bare_postgres_scheme_is_coerced():
    out = _normalize_pg_url("postgres://u:pw@host:5432/db")
    assert out.startswith("postgresql+asyncpg://")
    assert "u:pw@host:5432/db" in out  # credentials/host/db preserved


def test_sync_psycopg_driver_is_coerced_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        out = _normalize_pg_url("postgresql+psycopg2://u:pw@host/db")
    assert out.startswith("postgresql+asyncpg://")
    assert "coercing" in caplog.text.lower()


def test_already_async_url_is_untouched():
    raw = "postgresql+asyncpg://u:pw@host/db?ssl=require"
    assert _normalize_pg_url(raw) == raw


def test_local_default_is_untouched():
    raw = "postgresql+asyncpg://engine_room:engine_room@localhost:5433/engine_room"
    assert _normalize_pg_url(raw) == raw


def test_explicit_ssl_takes_precedence_over_sslmode():
    out = _normalize_pg_url(
        "postgresql+asyncpg://u:pw@h/db?ssl=verify-full&sslmode=require"
    )
    assert "ssl=verify-full" in out
    assert "sslmode" not in out


def test_non_postgres_url_passes_through():
    raw = "sqlite+aiosqlite:///./local.db"
    assert _normalize_pg_url(raw) == raw
