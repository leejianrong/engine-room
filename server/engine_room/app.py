"""FastAPI application factory.

V1 sub-step 1 exposes only /health; protocol (WS), spectator (SSE), and the
game engine mount here in later sub-steps.
"""

from fastapi import FastAPI

from . import __version__
from .matchmaking.queue import InMemoryQueue
from .ws.bot_endpoint import router as bot_router


def create_app() -> FastAPI:
    app = FastAPI(title="Engine Room", version=__version__)

    # Single-process MVP state (ADR-0020); each holds behind its interface (R6).
    app.state.matchmaking_queue = InMemoryQueue()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(bot_router)
    return app


app = create_app()
