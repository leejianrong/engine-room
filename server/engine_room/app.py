"""FastAPI application factory.

V1 sub-step 1 exposes only /health; protocol (WS), spectator (SSE), and the
game engine mount here in later sub-steps.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .auth.backend import auth_backend
from .auth.deps import fastapi_users
from .auth.oauth import make_github_oauth_router
from .auth.schemas import UserRead, UserUpdate
from .bots.authenticator import NullAuthenticator, PostgresBotAuthenticator
from .bots.routes import router as bots_router
from .config import settings
from .game.ambient import AmbientSupervisor, parse_pool
from .game.house_bots import (
    JIAN_001_ID,
    JIAN_001_NAME,
    JIAN_001_RATING,
    JIAN_002_ID,
    JIAN_002_NAME,
    JIAN_002_RATING,
    MinimaxBot,
    RandomBot,
)
from .game.house_clients import (
    HouseBotClientSupervisor,
    default_ambient_specs,
    make_db_key_provider,
    make_db_rating_provider,
)
from .game.registry import GameRegistry
from .matchmaking.elo import Windowing
from .matchmaking.launcher import GameLauncher
from .matchmaking.matcher import EloMatchmaker
from .matchmaking.queue import AlwaysPairQueue
from .observability import RequestIdMiddleware, render_metrics, setup_logging
from .persistence.finalize import PostgresFinalizer
from .persistence.reader import PostgresGameReader
from .pubsub.inproc import InProcPubSub
from .pubsub.redis import RedisPubSub
from .spectate.games import router as games_router
from .spectate.leaderboard import leaderboard_router
from .spectate.sse import router as spectate_router
from .tournaments.manager import TournamentManager
from .tournaments.routes import router as tournaments_router
from .ws.bot_endpoint import router as bot_router
from .ws.session_registry import SessionRegistry


class _SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html on a 404 (client-side routing).

    The SvelteKit SPA owns its own routes (e.g. `/watch`, `/bots`); a browser deep
    link to one of those is an unknown *file* to StaticFiles, so we serve index.html
    (200) and let the client router take over. Real assets (`/_app/...`) still serve
    normally. Mounted LAST (see `_mount_spa`) so every API route wins first.
    """

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def _mount_spa(app: FastAPI, static_dir: str) -> None:
    """Mount the built SPA at `/` iff `static_dir` holds an index.html.

    Gated on the build existing so the API-only app (dev/tests without a frontend
    build) still boots. Registered AFTER all API routers + `/docs` so the catch-all
    never shadows `/api/*`, `/health`, the WS/SSE endpoints, or the OpenAPI routes —
    Starlette matches routes in registration order, first match wins.
    """
    if not static_dir:
        return
    root = Path(static_dir)
    if not (root / "index.html").is_file():
        return
    app.mount("/", _SPAStaticFiles(directory=root, html=True), name="spa")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Start/stop the cross-worker SSE bus if it needs it (KAN-62). InProcPubSub has
    # no start/stop (nothing to run); RedisPubSub opens its shared connection +
    # pattern-reader here, mirroring how the matchmaking queue is started/stopped.
    if hasattr(app.state.pubsub, "start"):
        await app.state.pubsub.start()
    # Start/stop the background matchmaker loop (V3). No-op for AlwaysPairQueue.
    await app.state.matchmaking_queue.start()
    # Start/stop the tournament manager (KAN-56). Event-driven (start() is a no-op
    # at rest); stop() cancels any in-flight tournament run tasks on shutdown.
    await app.state.tournament_manager.start()
    # Start/stop the ambient house-vs-house feeder (V6). None when disabled.
    if app.state.ambient_supervisor is not None:
        await app.state.ambient_supervisor.start()
    # KAN-61: out-of-process house bots. Spawning is non-blocking and the clients
    # self-connect with retry, so this never deadlocks the lifespan. None unless the
    # flag is on. Exactly one of ambient_supervisor / house_client_supervisor is set.
    if app.state.house_client_supervisor is not None:
        await app.state.house_client_supervisor.start()
    try:
        yield
    finally:
        if app.state.house_client_supervisor is not None:
            await app.state.house_client_supervisor.stop()
        if app.state.ambient_supervisor is not None:
            await app.state.ambient_supervisor.stop()
        await app.state.tournament_manager.stop()
        await app.state.matchmaking_queue.stop()
        if hasattr(app.state.pubsub, "stop"):
            await app.state.pubsub.stop()


def _default_matcher(app: FastAPI, matcher_kwargs: dict | None) -> EloMatchmaker:
    kwargs = dict(
        windowing=Windowing(
            start=settings.mm_window_start,
            step=settings.mm_window_step,
            step_seconds=settings.mm_window_step_seconds,
            uncap_after_seconds=settings.mm_window_uncap_seconds,
        ),
        ticket_ttl_seconds=settings.mm_ticket_ttl_seconds,
        tick_interval_seconds=settings.mm_tick_interval_seconds,
        greeter_solo_wait_seconds=settings.mm_greeter_solo_wait_seconds,
        greeter_pools=settings.mm_greeter_pools,
    )
    if matcher_kwargs:
        kwargs.update(matcher_kwargs)
    return EloMatchmaker(
        app.state.game_registry,
        app.state.session_registry,
        app.state.game_launcher,
        app.state.house_bot,
        **kwargs,
    )


def create_app(
    finalizer=None,
    bot_authenticator=None,
    *,
    game_reader=None,
    ambient_games: int = 0,
    ambient_move_delay_seconds: float | None = None,
    always_pair: bool = False,
    matcher_kwargs: dict | None = None,
    hb_kwargs: dict | None = None,
    static_dir: str | None = None,
    house_bots_out_of_process: bool | None = None,
    house_bot_ws_url: str | None = None,
    house_bot_specs=None,
    house_bot_key_provider=None,
    ambient_rating_provider=None,
    tournament_session_factory=None,
) -> FastAPI:
    """Application factory.

    `finalizer` is the game-finalization hook (dependency-injected). Left None
    (the factory default) games are not persisted — handy for fast tests.

    `bot_authenticator` resolves a WS handshake's API key to a Bot identity
    (ADR-0014). Left None it defaults to a NullAuthenticator (rejects all — no
    accidental auth bypass); the production entrypoint wires PostgresBotAuthenticator
    and WS-seam tests inject an in-memory fake.

    `game_reader` is the spectator read side (lobby recently-finished + finished-
    game replay). Left None the endpoints serve the in-memory registry only.
    `ambient_games` (V6) is how many house-vs-house games the ambient supervisor
    keeps live so the lobby is never empty; 0 (default) disables it, production
    opts in via `settings.ambient_games`, and tests pass a value + tiny
    `ambient_move_delay_seconds` to exercise it deterministically.

    `always_pair` swaps the V3 Elo matcher for V1's synchronous always-pair-vs-
    house queue — used by game-loop/spectate tests that just need an instant game
    and don't exercise matchmaking. `matcher_kwargs` overrides the Elo matcher's
    settings-derived tuning (TTL, greeter, tick interval) for tests. `hb_kwargs`
    overrides the heartbeat tuning (`ping_interval_seconds`,
    `liveness_timeout_seconds`) so liveness tests use tiny values (V4).

    `static_dir` (V8) is the built SvelteKit SPA directory served same-origin (no
    nginx). None → `settings.static_dir` (empty in dev/tests → API-only, no mount).

    `house_bots_out_of_process` (KAN-61) overrides `settings.house_bots_out_of_process`
    (None → the setting). When True and `ambient_games > 0`, the ambient residents run
    as external `engineroom` SDK-client subprocesses instead of the in-process
    `AmbientSupervisor` (default). `house_bot_ws_url` is the URL those clients dial
    back into (None → the setting); `house_bot_specs` overrides the identities/personas
    (tests pass fast random-engine specs); `house_bot_key_provider` is the async
    `spec -> crbk_ key` provisioner (None → mint keys against the DB house rows —
    tests inject a DB-free provider returning known fake keys).
    """
    # Structured JSON logging + request/game-id context (KAN-63). Idempotent, so
    # safe under the many create_app() calls tests make. Configures the root logger
    # so the existing getLogger(__name__) call sites gain JSON output for free.
    setup_logging(level=settings.log_level, json_enabled=settings.log_json)

    app = FastAPI(title="Engine Room", version=__version__, lifespan=_lifespan)

    # Allow the SvelteKit dev server (and configured origins) to call the API,
    # e.g. the spectator EventSource. SSE GETs are simple requests (no preflight).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Request id per HTTP request (accept inbound X-Request-ID, else mint one),
    # bound into the log context + echoed on the response. Added after CORS so it
    # wraps outermost — the id is bound before anything else runs (KAN-63).
    app.add_middleware(RequestIdMiddleware)

    # Single-process MVP state (ADR-0020); matchmaking + pubsub sit behind their
    # interfaces (R6) so Redis-backed impls swap in at scale-out.
    app.state.game_registry = GameRegistry()
    # The ephemeral greeter persona (ephraim-bot): easy/random, one-and-done. Used
    # by the on-demand greeter (Kind-2) and V1's always-pair test queue.
    app.state.house_bot = RandomBot()
    # SSE fan-out bus (R6, ADR-0020). Empty ER_REDIS_URL (the default everywhere
    # today) → the single-process in-process bus. Set → the Redis-backed bus that
    # fans events across workers (KAN-62); its start/stop is hooked in _lifespan.
    app.state.pubsub = (
        RedisPubSub(settings.redis_url) if settings.redis_url else InProcPubSub()
    )
    app.state.finalizer = finalizer
    # Turns a paired Game into a running game: game_start fan-out + run_game
    # spawn (D-c). Shared by the always-pair path and the V3 matcher.
    app.state.game_launcher = GameLauncher(
        app.state.pubsub,
        game_registry=app.state.game_registry,
        finalizer=finalizer,
        house_move_delay=settings.house_move_delay_seconds,
    )
    # V6 ambient house-vs-house feeder (ADR-0022 Kind-1): keeps `ambient_games`
    # games live so the lobby is never empty. Off by default (0) — production opts
    # in via settings; tests set a value explicitly. Uses its own launcher with an
    # ambient move delay so the games are watchable independent of the greeter's
    # house pacing. Launched with the same finalizer → rated + persisted (Q4).
    # The permanent ambient bots (jian-bot-001/002): minimax + alpha-beta, rated +
    # persisted lobby residents. Distinct identities from the greeter (ephraim).
    depth = settings.ambient_minimax_depth
    app.state.ambient_bots = (
        MinimaxBot(id=JIAN_001_ID, name=JIAN_001_NAME, rating=JIAN_001_RATING, depth=depth),
        MinimaxBot(id=JIAN_002_ID, name=JIAN_002_NAME, rating=JIAN_002_RATING, depth=depth),
    )
    oop_house = (
        settings.house_bots_out_of_process
        if house_bots_out_of_process is None
        else house_bots_out_of_process
    )
    # KAN-61: exactly one house-bot driver is active. Flag OFF (default) → the
    # in-process AmbientSupervisor below (unchanged). Flag ON → the out-of-process
    # SDK-client supervisor instead; the in-process feeder is left disabled so
    # games aren't double-produced. The greeter stays in-process either way.
    app.state.house_client_supervisor = None
    if ambient_games > 0 and oop_house:
        app.state.ambient_supervisor = None
        tc = parse_pool(settings.ambient_pools[0])
        specs = house_bot_specs or default_ambient_specs(
            depth=settings.ambient_minimax_depth,
            time_control=(tc.base_seconds, tc.increment_seconds),
        )
        app.state.house_client_supervisor = HouseBotClientSupervisor(
            specs,
            house_bot_ws_url or settings.house_bot_ws_url,
            key_provider=house_bot_key_provider or make_db_key_provider(),
        )
    elif ambient_games > 0:
        delay = (
            ambient_move_delay_seconds
            if ambient_move_delay_seconds is not None
            else settings.ambient_move_delay_seconds
        )
        ambient_launcher = GameLauncher(
            app.state.pubsub,
            game_registry=app.state.game_registry,
            finalizer=finalizer,
            house_move_delay=delay,
        )
        app.state.ambient_supervisor = AmbientSupervisor(
            app.state.game_registry,
            ambient_launcher,
            app.state.ambient_bots[0],
            app.state.ambient_bots[1],
            n=ambient_games,
            time_controls=[parse_pool(p) for p in settings.ambient_pools],
            rating_provider=ambient_rating_provider,
        )
    else:
        app.state.ambient_supervisor = None
    # V6 spectator read side (lobby recently-finished + finished-game replay).
    # DI mirrors the finalizer: None (fast tests) → endpoints serve the in-memory
    # registry only; production wires PostgresGameReader.
    app.state.game_reader = game_reader
    app.state.lobby_finished_limit = settings.lobby_finished_limit
    app.state.bot_authenticator = bot_authenticator or NullAuthenticator()
    # One live session per bot; newest-wins replacement (ADR-0016 A6).
    app.state.session_registry = SessionRegistry()
    # V4 heartbeat tuning (§10): per-connection ping interval + liveness timeout.
    # Settings defaults (10s / 30s); tests inject tiny values via hb_kwargs.
    hb = {
        "ping_interval_seconds": settings.hb_ping_interval_seconds,
        "liveness_timeout_seconds": settings.hb_liveness_timeout_seconds,
    }
    if hb_kwargs:
        hb.update(hb_kwargs)
    app.state.hb_ping_interval_seconds = hb["ping_interval_seconds"]
    app.state.hb_liveness_timeout_seconds = hb["liveness_timeout_seconds"]
    # V3: real Elo pools behind MatchmakingQueue (R6); the loop is started by the
    # lifespan and delivers game_start asynchronously (ADR-0025). `always_pair`
    # keeps V1's synchronous house pairing for game-loop/spectate tests.
    if always_pair:
        app.state.matchmaking_queue = AlwaysPairQueue(
            app.state.game_registry, app.state.house_bot
        )
    else:
        app.state.matchmaking_queue = _default_matcher(app, matcher_kwargs)

    # KAN-56 tournaments: enrollment (via a tournament-tagged seek) + running a
    # round-robin over the shared GameLauncher, standings persisted. Single-process
    # / in-memory-orchestrated like the matcher. Its DB writes use SessionLocal by
    # default; tests inject a container-bound factory (mirrors the finalizer DI).
    tm_kwargs = {}
    if tournament_session_factory is not None:
        tm_kwargs["session_factory"] = tournament_session_factory
    app.state.tournament_manager = TournamentManager(
        app.state.game_registry,
        app.state.session_registry,
        app.state.game_launcher,
        **tm_kwargs,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Prometheus text exposition (KAN-63). Registered BEFORE the SPA catch-all
    # mount so it isn't swallowed by the client-routing fallback. Unauthenticated
    # for now (locking it down + an admin view are the deferred follow-ups).
    if settings.metrics_enabled:

        @app.get("/metrics")
        async def metrics():
            return render_metrics()

    app.include_router(bot_router)
    app.include_router(spectate_router)
    app.include_router(games_router)
    app.include_router(leaderboard_router)

    # Human identity REST surface (V2 / slice A2). Bot CRUD mounts in sub-step 3.
    app.include_router(
        make_github_oauth_router(),
        prefix="/api/auth/github",
        tags=["auth"],
    )
    # Login/logout for the cookie session backend (KAN-64). We only use `/logout`
    # (the SPA's Sign-out button POSTs it to clear the `er_session` cookie); the
    # human /login flow is GitHub OAuth above. Cookie auth reads the cookie
    # automatically, so `current_active_user` needs nothing else here.
    app.include_router(
        fastapi_users.get_auth_router(auth_backend),
        prefix="/api/auth/jwt",
        tags=["auth"],
    )
    app.include_router(
        fastapi_users.get_users_router(UserRead, UserUpdate),
        prefix="/api/users",
        tags=["users"],
    )
    app.include_router(bots_router)
    app.include_router(tournaments_router)

    # Same-origin SPA (V8, KAN-68): mount the built SvelteKit app LAST so its
    # client-routing catch-all never shadows the API/WS/SSE routes or /docs above.
    _mount_spa(app, settings.static_dir if static_dir is None else static_dir)
    return app


# Production wiring: persist finished games to Postgres; authenticate real
# per-bot API keys at the WS handshake.
app = create_app(
    finalizer=PostgresFinalizer(),
    bot_authenticator=PostgresBotAuthenticator(),
    game_reader=PostgresGameReader(),
    ambient_games=settings.ambient_games,
    ambient_rating_provider=make_db_rating_provider(),
)
