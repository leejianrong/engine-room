"""Runtime settings. Environment variables are prefixed ER_ (e.g. ER_DATABASE_URL)."""

import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

_ASYNC_PG_DRIVER = "postgresql+asyncpg"


def _normalize_pg_url(raw: str) -> str:
    """Coerce a Postgres URL to the async driver the app requires and translate
    libpq-style SSL query params to what asyncpg understands.

    The app is async-only (SQLAlchemy asyncpg). A bare ``postgresql://`` URL
    resolves to the *sync* psycopg2 driver (not shipped in the image) — the
    common footgun when pasting a Neon/Heroku connection string. This makes such
    a URL just work, and warns so the operator can fix the source:

    - ``postgresql://`` / ``postgres://`` / ``postgresql+psycopg2://`` → ``postgresql+asyncpg://``
    - ``sslmode=require`` → ``ssl=require`` (asyncpg's spelling; used by Neon)
    - drop ``channel_binding`` (asyncpg negotiates it itself and rejects the kwarg)

    Non-Postgres URLs pass through untouched.
    """
    url = make_url(raw)
    if not url.drivername.startswith("postgres"):
        return raw

    changed = False
    if url.drivername != _ASYNC_PG_DRIVER:
        logger.warning(
            "ER_DATABASE_URL uses driver %r; coercing to %r — this app requires the "
            "async driver. Set ER_DATABASE_URL to a %r URL to silence this.",
            url.drivername,
            _ASYNC_PG_DRIVER,
            _ASYNC_PG_DRIVER,
        )
        url = url.set(drivername=_ASYNC_PG_DRIVER)
        changed = True

    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    if sslmode is not None:
        query.setdefault("ssl", sslmode)  # keep an explicit ssl= if already present
        changed = True
    if query.pop("channel_binding", None) is not None:
        changed = True

    if changed:
        return url.set(query=query).render_as_string(hide_password=False)
    return raw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ER_", env_file=".env", extra="ignore")

    # Postgres (async asyncpg driver). Matches docker-compose.yml defaults.
    # Normalized by `_normalize_pg_url` so a raw Neon/Heroku `postgresql://…` URL
    # (sync driver, `sslmode`/`channel_binding` params) is coerced to work.
    database_url: str = (
        "postgresql+asyncpg://engine_room:engine_room@localhost:5433/engine_room"
    )

    @field_validator("database_url")
    @classmethod
    def _coerce_async_pg(cls, v: str) -> str:
        return _normalize_pg_url(v)

    # --- V2 identity (slice A2) ---
    # (V1's stub `dev_bot_token` is gone — the WS handshake now authenticates real
    # per-bot API keys via PostgresBotAuthenticator; ER_DEV_BOT_TOKEN is ignored.)
    # Human login sessions: FastAPI-Users stateless JWT (D-l). Signs the JWT and
    # the OAuth `state` param. MUST be overridden in production (ER_AUTH_SECRET).
    auth_secret: str = "dev-auth-secret-change-me-in-production-0123456789"  # ≥32B
    auth_jwt_lifetime_seconds: int = 60 * 60 * 24  # 1 day

    # Per-bot API keys: HMAC-SHA256 pepper (D-k / ADR-0014). MUST be overridden in
    # production (ER_API_KEY_PEPPER) — the pepper is what makes a DB leak useless.
    api_key_pepper: str = "dev-api-key-pepper-change-me-in-production-0123456789"

    # GitHub OAuth app (ADR-0013). Empty in dev/CI (tests stub the provider, D-i);
    # set the real values to run a live browser login.
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_redirect_url: str | None = None

    # The OAuth CSRF cookie is `Secure` by default (production runs behind HTTPS).
    # Set ER_OAUTH_COOKIE_SECURE=false to exercise the real GitHub flow over plain
    # http://localhost in dev, where a Secure cookie would otherwise be dropped.
    oauth_cookie_secure: bool = True

    # Browser origins allowed to call the API (spectator SSE from the SvelteKit
    # dev server on :5174). Override with ER_CORS_ALLOW_ORIGINS as a JSON list.
    cors_allow_origins: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]


settings = Settings()
