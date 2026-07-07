"""Runtime settings. Environment variables are prefixed ER_ (e.g. ER_DATABASE_URL)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ER_", env_file=".env", extra="ignore")

    # Postgres (asyncpg driver). Matches docker-compose.yml defaults.
    database_url: str = (
        "postgresql+asyncpg://engine_room:engine_room@localhost:5433/engine_room"
    )

    # V1 stub auth (ADR-0014 real keys arrive in V2 / slice A2). Any bot presenting
    # this bearer token at the WebSocket handshake is accepted.
    dev_bot_token: str = "dev-token"


settings = Settings()
