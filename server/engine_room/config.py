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

    # Browser origins allowed to call the API. Since V8 the SPA is served from THIS
    # app (same-origin), so CORS is no longer load-bearing in prod — it's kept only
    # for anyone hosting the frontend on a separate origin. The dev-server default
    # covers a bare `npm run dev` without the Vite proxy. Override with
    # ER_CORS_ALLOW_ORIGINS as a JSON list.
    cors_allow_origins: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    # Built SvelteKit SPA directory served same-origin by this app (V8, KAN-68).
    # When set to a dir containing index.html, uvicorn serves the static assets and
    # an SPA fallback (no nginx). Empty (dev/tests without a build) → not mounted,
    # so the API-only app still boots. The backend image bakes the build in and sets
    # ER_STATIC_DIR to it.
    static_dir: str = ""

    # --- KAN-63 observability (first slice) ---
    # Root log level and whether logs are emitted as one JSON object per line
    # (structured, request_id/game_id threaded) vs a plain human line. JSON is the
    # prod default; flip ER_LOG_JSON=false locally for readable `--reload` output.
    log_level: str = "INFO"
    log_json: bool = True
    # Expose the Prometheus `/metrics` endpoint (text exposition). Unauthenticated
    # for now — locking it down / an admin view is the deferred KAN-63 follow-up.
    metrics_enabled: bool = True

    # --- V3 matchmaking (slice A3, ADR-0011/0012/0016 E8) ---
    # Elo widening window: half-width starts at ±`mm_window_start`, grows by
    # `mm_window_step` every `mm_window_step_seconds`, and is uncapped (∞ — pair
    # anyone) once a ticket has waited `mm_window_uncap_seconds`. Read-only in V3
    # (ratings on `bots.rating`); rating *writes* + K-factor are V5.
    mm_window_start: int = 100
    mm_window_step: int = 100
    mm_window_step_seconds: float = 10.0
    mm_window_uncap_seconds: float = 60.0
    # Ticket max-wait: past this a lonely seek → seek_ended{expired} (E8, 120s).
    mm_ticket_ttl_seconds: float = 120.0
    # Matcher loop wake interval (also nudged by each seek/cancel). Small so
    # widening/TTL fire promptly; tests set a tiny value.
    mm_tick_interval_seconds: float = 0.5
    # On-demand greeter house game (Kind 2, D-i): a ticket alone in a greeter pool
    # for `mm_greeter_solo_wait_seconds` gets a house opponent (ADR-0022). Pools
    # NOT listed here (e.g. 5+0 "300+0") never get a greeter → a lonely seek there
    # expires, which is the V3 expiry demo. Keys are "<base>+<increment>" seconds.
    # KAN-57: bullet 1+0 ("60+0") and an increment pool 2+1 ("120+1") join 3+0 so a
    # lone seeker in either gets a greeter game (the greeter launcher runs at 0
    # delay, so a short bullet clock plays cleanly). Seeks in any TC are always
    # accepted (the endpoint doesn't whitelist); this only controls the greeter.
    mm_greeter_solo_wait_seconds: float = 3.0
    mm_greeter_pools: list[str] = ["180+0", "60+0", "120+1"]

    # --- V4 resilience (slice A4, ADR-0025 #3 / PROTOCOL §10) ---
    # Heartbeat: the server pings each live bot socket every `hb_ping_interval_seconds`;
    # a socket that has not sent a `pong` within `hb_liveness_timeout_seconds` is
    # treated as dead and closed (turning a half-dead socket into a real disconnect).
    # Liveness is used ONLY to detect mutual abandonment (both seats gone → ABORTED);
    # a single disconnected bot is never forfeited by heartbeat — only by its clock.
    # Tests set tiny values (e.g. 0.05 / 0.15) to exercise a timeout without waiting.
    hb_ping_interval_seconds: float = 10.0
    hb_liveness_timeout_seconds: float = 30.0  # ~3 missed pings

    # --- V5 outcomes & ratings (slice A5, ADR-0011 / 0016 E8) ---
    # Elo update on FINISHED (ABORTED never rates). K is larger while a bot is
    # provisional (its first `elo_provisional_games` rated games) so early ratings
    # converge faster; smaller afterwards. Single global rating per bot at MVP
    # (per-time-control deferred). Initial rating is the bots.rating default (1200).
    elo_k_provisional: int = 32
    elo_k_default: int = 16
    elo_provisional_games: int = 30

    # --- V6 spectator UX (slice A6, ADR-0015/0022) ---
    # Lobby: how many recently-finished games GET /api/games returns from Postgres
    # (newest first), alongside all active games from the in-memory registry (D-e).
    lobby_finished_limit: int = 20
    # Ambient house-vs-house games (ADR-0022 Kind-1) kept live so the lobby is
    # never empty. 0 disables (CI/unit default via create_app). Rated + persisted
    # via the normal launcher (V6 Q4). Move delay makes them watchable.
    ambient_games: int = 2
    ambient_move_delay_seconds: float = 1.0
    # Time-control rotation for ambient house-vs-house games (KAN-57): the
    # supervisor round-robins these across its `ambient_games` slots, so the lobby
    # autonomously shows a mix and the increment path runs in real, persisted games.
    # "<base>+<increment>" seconds — 3+0, bullet 1+0, and 2+1 (increment). A short
    # bullet base (60s) survives the 1s move delay fine (~60 moves/side before flag).
    ambient_pools: list[str] = ["180+0", "60+0", "120+1"]
    # The permanent ambient bots (jian-bot-NNN) play minimax + alpha-beta; this is
    # the search depth. Pure-Python CPU grows with depth, so dial it down on a small
    # VM (ER_AMBIENT_MINIMAX_DEPTH). Depth 3 ≈ 0.1-0.3s/move.
    ambient_minimax_depth: int = 3

    # Artificial pause before the in-process house bot replies. Default 0 (instant,
    # no production impact); local dev sets ~0.5s so house games are watchable move
    # by move. Charged to the house's own clock — safe on a Blitz clock.
    house_move_delay_seconds: float = 0.0

    # --- KAN-61: out-of-process house bots (additive, config-gated) ---
    # FALSE (default): behaviour is exactly as today — the in-process
    # AmbientSupervisor keeps the lobby's house-vs-house games live, and the greeter
    # (ephraim) is synthesized in-process by the matcher. The production deploy is
    # unchanged.
    # TRUE: the permanent ambient residents (jian-bot-001/002) instead run as
    # EXTERNAL `engineroom` SDK WebSocket clients in supervised subprocesses — they
    # authenticate the real bot WS endpoint with `crbk_` keys and pair with each
    # other through the normal matcher, so the games are real, persisted, and rated.
    # The server never imports the SDK (ADR-0021): it only manages subprocesses. The
    # on-demand greeter stays in-process either way (deferred — see the PR).
    house_bots_out_of_process: bool = False
    # The WS URL the out-of-process house-bot clients dial back into (this same
    # server). Must be reachable from the subprocess; defaults to the local uvicorn
    # port. The SDK client retries/backoff-connects, so it tolerates the server not
    # yet accepting when the subprocess launches (self-connect timing, ADR-0025 #3).
    house_bot_ws_url: str = "ws://127.0.0.1:8001/api/bot/v1"


settings = Settings()
