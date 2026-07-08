"""The bot WebSocket endpoint — PROTOCOL.md §3-5 (handshake + seek).

V1 sub-step 2 scope: stub-auth (dev token), `hello`->`welcome`, protocol-version
check, and `seek`->`seek_ack` (enqueue only). Pairing, the game loop, and
reconnect arrive in later sub-steps.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..game.game import Game
from ..game.worker import run_game
from ..ids import new_id
from ..protocol.messages import (
    BotInfo,
    Clocks,
    Error,
    GameStart,
    Hello,
    Move,
    ProtocolError,
    Seek,
    SeekAck,
    Welcome,
    parse_client_message,
)
from .session import Session

router = APIRouter()

# Keep strong refs to in-flight game tasks so they aren't garbage-collected.
_running_games: set[asyncio.Task] = set()

SERVER_PROTOCOL_VERSION = "1.0"
SUPPORTED_VERSIONS = {"1.0"}

# WebSocket close codes
_CLOSE_POLICY_VIOLATION = 1008
_CLOSE_PROTOCOL_ERROR = 1002


def _bearer_token(websocket: WebSocket) -> str | None:
    header = websocket.headers.get("authorization")
    if not header:
        return None
    parts = header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


@router.websocket("/api/bot/v1")
async def bot_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    # --- auth (stub: single dev token; real hashed keys in V2, ADR-0014) ---
    if _bearer_token(websocket) != settings.dev_bot_token:
        await websocket.send_text(
            Error(code="UNAUTHORIZED", message="bad or missing API key", fatal=True).model_dump_json()
        )
        await websocket.close(_CLOSE_POLICY_VIOLATION)
        return

    # V1: one logical stub bot behind the dev token; real identity comes in V2.
    session = Session(
        websocket,
        bot=BotInfo(id="bot_dev", name="dev-bot", rating=1200),
        session_id=new_id("sess"),
    )

    # --- handshake: first frame must be hello ---
    try:
        first = await websocket.receive_text()
    except WebSocketDisconnect:
        return
    try:
        msg = parse_client_message(first)
    except ProtocolError as exc:
        await session.send(Error(code=exc.code, message=exc.message, fatal=True))
        await websocket.close(_CLOSE_PROTOCOL_ERROR)
        return
    if not isinstance(msg, Hello):
        await session.send(Error(code="INVALID_MESSAGE", message="expected hello first", fatal=True))
        await websocket.close(_CLOSE_PROTOCOL_ERROR)
        return
    if msg.protocol_version not in SUPPORTED_VERSIONS:
        await session.send(
            Error(
                code="VERSION_UNSUPPORTED",
                message=f"server supports {sorted(SUPPORTED_VERSIONS)}",
                fatal=True,
            )
        )
        await websocket.close(_CLOSE_PROTOCOL_ERROR)
        return

    await session.send(
        Welcome(
            protocol_version=SERVER_PROTOCOL_VERSION,
            session_id=session.session_id,
            bot=session.bot,
            active_game=None,
        )
    )

    # --- main receive loop ---
    queue = websocket.app.state.matchmaking_queue
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = parse_client_message(raw)
            except ProtocolError as exc:
                # Non-move junk: report and keep the connection open (ADR-0016).
                await session.send(Error(code=exc.code, message=exc.message, fatal=False))
                continue

            if isinstance(msg, Seek):
                result = await queue.seek(session, msg.time_control)
                await session.send(SeekAck(id=msg.id, seek_id=result.seek_id, status="queued"))
                if result.game is not None:
                    await session.send(_game_start_for(result.game, session))
                    task = asyncio.create_task(run_game(result.game))
                    _running_games.add(task)
                    task.add_done_callback(_running_games.discard)
            elif isinstance(msg, Move):
                # Single socket reader: hand in-game moves to the game loop.
                await session.inbound.put(msg)
            elif isinstance(msg, Hello):
                await session.send(
                    Error(code="INVALID_MESSAGE", message="already handshaken", fatal=False)
                )
            else:  # pragma: no cover - no other client models yet
                await session.send(Error(code="INVALID_MESSAGE", message="unhandled type", fatal=False))
    except WebSocketDisconnect:
        # Reconnect / seat cleanup on disconnect arrives in V4 (resilience).
        return


def _game_start_for(game: Game, session: Session) -> GameStart:
    """Build game_start from the given session's perspective."""
    if game.white.session is session:
        your_color, opponent = "white", game.black.bot
    else:
        your_color, opponent = "black", game.white.bot
    return GameStart(
        game_id=game.id,
        your_color=your_color,
        opponent=opponent,
        time_control=game.time_control,
        initial_fen=game.initial_fen,
        clocks=Clocks(white_ms=game.white_ms, black_ms=game.black_ms),
    )
