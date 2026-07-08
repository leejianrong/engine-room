"""FastAPI application factory.

V1 sub-step 1 exposes only /health; protocol (WS), spectator (SSE), and the
game engine mount here in later sub-steps.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .auth.deps import fastapi_users
from .auth.oauth import make_github_oauth_router
from .auth.schemas import UserRead, UserUpdate
from .config import settings
from .game.house_bots import RandomBot
from .game.registry import GameRegistry
from .matchmaking.queue import AlwaysPairQueue
from .persistence.finalize import PostgresFinalizer
from .pubsub.inproc import InProcPubSub
from .spectate.sse import router as spectate_router
from .ws.bot_endpoint import router as bot_router


def create_app(finalizer=None) -> FastAPI:
    """Application factory.

    `finalizer` is the game-finalization hook (dependency-injected). Left None
    (the factory default) games are not persisted — handy for fast tests. The
    production entrypoint below wires a PostgresFinalizer.
    """
    app = FastAPI(title="Engine Room", version=__version__)

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
    app.state.matchmaking_queue = AlwaysPairQueue(
        app.state.game_registry, app.state.house_bot
    )
    app.state.finalizer = finalizer

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
    return app


# Production wiring: persist finished games to Postgres.
app = create_app(finalizer=PostgresFinalizer())
