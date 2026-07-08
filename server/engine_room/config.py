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
    #
    # V2 (slice A2) authenticates real per-bot keys instead; the WS endpoint no
    # longer consults this. Retained so the field is not a breaking removal and so
    # any lingering tooling that sets ER_DEV_BOT_TOKEN doesn't error.
    dev_bot_token: str = "dev-token"

    # --- V2 identity (slice A2) ---
    # Human login sessions: FastAPI-Users stateless JWT (D-l). Signs the JWT and
    # the OAuth `state` param. MUST be overridden in production (ER_AUTH_SECRET).
    auth_secret: str = "dev-auth-secret-change-me"
    auth_jwt_lifetime_seconds: int = 60 * 60 * 24  # 1 day

    # Per-bot API keys: HMAC-SHA256 pepper (D-k / ADR-0014). MUST be overridden in
    # production (ER_API_KEY_PEPPER) — the pepper is what makes a DB leak useless.
    api_key_pepper: str = "dev-api-key-pepper-change-me"

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
