"""FastAPI application factory.

V1 sub-step 1 exposes only /health; protocol (WS), spectator (SSE), and the
game engine mount here in later sub-steps.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .auth.deps import fastapi_users
from .auth.oauth import make_github_oauth_router
from .auth.schemas import UserRead, UserUpdate
from .bots.authenticator import NullAuthenticator, PostgresBotAuthenticator
from .bots.routes import router as bots_router
from .config import settings
from .game.house_bots import RandomBot
from .game.registry import GameRegistry
from .matchmaking.elo import Windowing
from .matchmaking.launcher import GameLauncher
from .matchmaking.matcher import EloMatchmaker
from .matchmaking.queue import AlwaysPairQueue
from .persistence.finalize import PostgresFinalizer
from .pubsub.inproc import InProcPubSub
from .spectate.sse import router as spectate_router
from .ws.bot_endpoint import router as bot_router
from .ws.session_registry import SessionRegistry


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Start/stop the background matchmaker loop (V3). No-op for AlwaysPairQueue.
    await app.state.matchmaking_queue.start()
    try:
        yield
    finally:
        await app.state.matchmaking_queue.stop()


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
    always_pair: bool = False,
    matcher_kwargs: dict | None = None,
) -> FastAPI:
    """Application factory.

    `finalizer` is the game-finalization hook (dependency-injected). Left None
    (the factory default) games are not persisted — handy for fast tests.

    `bot_authenticator` resolves a WS handshake's API key to a Bot identity
    (ADR-0014). Left None it defaults to a NullAuthenticator (rejects all — no
    accidental auth bypass); the production entrypoint wires PostgresBotAuthenticator
    and WS-seam tests inject an in-memory fake.

    `always_pair` swaps the V3 Elo matcher for V1's synchronous always-pair-vs-
    house queue — used by game-loop/spectate tests that just need an instant game
    and don't exercise matchmaking. `matcher_kwargs` overrides the Elo matcher's
    settings-derived tuning (TTL, greeter, tick interval) for tests.
    """
    app = FastAPI(title="Engine Room", version=__version__, lifespan=_lifespan)

    # Allow the SvelteKit dev server (and configured origins) to call the API,
    # e.g. the spectator EventSource. SSE GETs are simple requests (no preflight).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Single-process MVP state (ADR-0020); matchmaking + pubsub sit behind their
    # interfaces (R6) so Redis-backed impls swap in at scale-out.
    app.state.game_registry = GameRegistry()
    app.state.house_bot = RandomBot()
    app.state.pubsub = InProcPubSub()
    app.state.finalizer = finalizer
    # Turns a paired Game into a running game: game_start fan-out + run_game
    # spawn (D-c). Shared by the always-pair path and the V3 matcher.
    app.state.game_launcher = GameLauncher(app.state.pubsub, finalizer)
    app.state.bot_authenticator = bot_authenticator or NullAuthenticator()
    # One live session per bot; newest-wins replacement (ADR-0016 A6).
    app.state.session_registry = SessionRegistry()
    # V3: real Elo pools behind MatchmakingQueue (R6); the loop is started by the
    # lifespan and delivers game_start asynchronously (ADR-0025). `always_pair`
    # keeps V1's synchronous house pairing for game-loop/spectate tests.
    if always_pair:
        app.state.matchmaking_queue = AlwaysPairQueue(
            app.state.game_registry, app.state.house_bot
        )
    else:
        app.state.matchmaking_queue = _default_matcher(app, matcher_kwargs)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(bot_router)
    app.include_router(spectate_router)

    # Human identity REST surface (V2 / slice A2). Bot CRUD mounts in sub-step 3.
    app.include_router(
        make_github_oauth_router(),
        prefix="/api/auth/github",
        tags=["auth"],
    )
    app.include_router(
        fastapi_users.get_users_router(UserRead, UserUpdate),
        prefix="/api/users",
        tags=["users"],
    )
    app.include_router(bots_router)
    return app


# Production wiring: persist finished games to Postgres; authenticate real
# per-bot API keys at the WS handshake.
app = create_app(
    finalizer=PostgresFinalizer(),
    bot_authenticator=PostgresBotAuthenticator(),
)
