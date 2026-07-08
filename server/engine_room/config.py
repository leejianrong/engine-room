"""Runtime settings. Environment variables are prefixed ER_ (e.g. ER_DATABASE_URL)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ER_", env_file=".env", extra="ignore")

    # Postgres (asyncpg driver). Matches docker-compose.yml defaults.
    database_url: str = (
        "postgresql+asyncpg://engine_room:engine_room@localhost:5433/engine_room"
    )

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

    # Browser origins allowed to call the API (spectator SSE from the SvelteKit
    # dev server on :5174). Override with ER_CORS_ALLOW_ORIGINS as a JSON list.
    cors_allow_origins: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]


settings = Settings()
