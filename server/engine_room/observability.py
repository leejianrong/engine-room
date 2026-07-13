"""Observability: structured JSON logging, request/game-id context, and /metrics.

KAN-63 (first slice). Three pieces, kept in this one module:

1. **JSON logging** — `setup_logging()` points the root logger at a single stderr
   handler whose `JsonFormatter` emits one JSON object per line (ts, level, logger,
   msg, plus any bound `request_id`/`game_id` and any `extra=` fields). Existing
   ad-hoc `logging.getLogger(__name__)` call sites keep working unchanged — they
   just gain JSON output + the bound context for free.
2. **Context ids** — two `contextvars` (`request_id`, `game_id`) the formatter reads,
   so nothing has to pass ids through call signatures. HTTP requests bind
   `request_id` via `RequestIdMiddleware`; the game launcher binds `game_id` around
   a launch (which the `run_game` task inherits, since `create_task` copies the
   context).
3. **Metrics** — a few Prometheus counters/gauges (defined once at module import, so
   re-`create_app()` in tests never double-registers) rendered at `/metrics` in the
   standard text exposition format. The default registry also carries process/GC
   metrics for free.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .ids import new_id

# --- context ids ------------------------------------------------------------

# Read by JsonFormatter; None when unbound. Set per HTTP request (middleware) and
# per game (launcher). contextvars are task-local and copied into child tasks at
# `create_task`, so a game_id bound before spawning `run_game` follows the loop.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
game_id_var: ContextVar[str | None] = ContextVar("game_id", default=None)


def bind_game_id(game_id: str):
    """Bind `game_id` in the current context; returns the token for `reset_game_id`."""
    return game_id_var.set(game_id)


def reset_game_id(token) -> None:
    game_id_var.reset(token)


# --- JSON logging -----------------------------------------------------------

# Standard LogRecord attributes we don't echo (everything else on the record is
# treated as caller-supplied `extra=` and included in the JSON line).
_STD_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Formats a LogRecord as a single-line JSON object with bound context."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid is not None:
            payload["request_id"] = rid
        gid = game_id_var.get()
        if gid is not None:
            payload["game_id"] = gid
        # Any non-standard attributes are caller-supplied via `extra=`.
        for key, value in record.__dict__.items():
            if key not in _STD_RECORD_ATTRS and not key.startswith("_"):
                payload.setdefault(key, value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", json_enabled: bool = True) -> None:
    """Configure the root logger with a single stderr handler.

    Idempotent — safe to call from every `create_app()` (tests build many apps):
    it replaces the root handlers rather than stacking them. `json_enabled=False`
    falls back to a plain human formatter (handy for a local `--reload` session).
    """
    handler = logging.StreamHandler(sys.stderr)
    if json_enabled:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


# --- metrics ----------------------------------------------------------------

# Defined once at import (module cache) so repeated `create_app()` calls in tests
# reuse the same collectors instead of raising "Duplicated timeseries".
HTTP_REQUESTS = Counter(
    "er_http_requests_total",
    "HTTP requests handled, by method and response status.",
    ["method", "status"],
)
GAMES_ACTIVE = Gauge(
    "er_games_active",
    "Games currently in flight (launched, not yet finished).",
)
GAMES_STARTED = Counter(
    "er_games_started_total",
    "Games launched since process start.",
)
GAMES_FINISHED = Counter(
    "er_games_finished_total",
    "Games that reached a terminal (run loop returned) since process start.",
)


def record_game_started() -> None:
    GAMES_STARTED.inc()
    GAMES_ACTIVE.inc()


def record_game_finished() -> None:
    GAMES_FINISHED.inc()
    GAMES_ACTIVE.dec()


def render_metrics() -> Response:
    """Render the Prometheus text exposition of the default registry."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --- request-id middleware --------------------------------------------------


class RequestIdMiddleware:
    """Pure-ASGI middleware: bind a request id per HTTP request + count requests.

    Kept as raw ASGI (not `BaseHTTPMiddleware`) so it doesn't buffer the SSE
    streaming responses the spectator endpoints emit. Non-HTTP scopes (WebSocket,
    lifespan) pass straight through. Honours an inbound `X-Request-ID`, else mints
    one via the repo id helper, stores it in `request_id_var` (so logs during the
    request carry it), and echoes it on the response header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        inbound = headers.get(b"x-request-id")
        rid = inbound.decode("latin-1") if inbound else new_id("req")
        token = request_id_var.set(rid)
        captured = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", rid.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            HTTP_REQUESTS.labels(
                method=scope.get("method", "UNKNOWN"), status=str(captured["status"])
            ).inc()
            request_id_var.reset(token)
