"""The bot WebSocket endpoint — PROTOCOL.md §3-5 (handshake + seek).

Handshake authenticates the bot's real API key (ADR-0014; injected
`BotAuthenticator`), binds the Session to the real Bot identity, and enforces
newest-wins session replacement (ADR-0016 A6). `hello`->`welcome`,
protocol-version check, and `seek`->`seek_ack`/pairing follow. Reconnect-resume
of a mid-game seat is V4.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ids import new_id
from ..protocol.messages import (
    Error,
    Hello,
    Move,
    ProtocolError,
    Seek,
    SeekAck,
    SeekCancel,
    Welcome,
    parse_client_message,
)
from .session import Session

router = APIRouter()

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

    # --- auth: real per-bot API key (ADR-0014), injected authenticator (D-c) ---
    bot_info = await websocket.app.state.bot_authenticator.authenticate(
        _bearer_token(websocket) or ""
    )
    if bot_info is None:
        unauthorized = Error(code="UNAUTHORIZED", message="bad or missing API key", fatal=True)
        await websocket.send_text(unauthorized.model_dump_json())
        await websocket.close(_CLOSE_POLICY_VIOLATION)
        return

    session = Session(websocket, bot=bot_info, session_id=new_id("sess"))

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
        await session.send(
            Error(code="INVALID_MESSAGE", message="expected hello first", fatal=True)
        )
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

    # --- newest-wins: this becomes the bot's live session; close the prior one
    # (ADR-0016 A6). Best-effort — the old socket may already be half-dead. ---
    registry = websocket.app.state.session_registry
    replaced = registry.register(session)
    if replaced is not None:
        await replaced.terminate("replaced by a newer connection")

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
                # Async matcher path (V3): game_start arrives later, via the
                # launcher. The always-pair path returns an inline game whose
                # launch we drive here (kept working until sub-step 4 swaps it).
                if result.game is not None:
                    await websocket.app.state.game_launcher.launch(result.game)
            elif isinstance(msg, SeekCancel):
                # Withdraw a waiting seek (ADR-0016 E8); matcher → seek_ended.
                await queue.cancel(msg.seek_id)
            elif isinstance(msg, Move):
                # Single socket reader: hand in-game moves to the game loop.
                await session.inbound.put(msg)
            elif isinstance(msg, Hello):
                await session.send(
                    Error(code="INVALID_MESSAGE", message="already handshaken", fatal=False)
                )
            else:  # pragma: no cover - no other client models yet
                await session.send(
                    Error(code="INVALID_MESSAGE", message="unhandled type", fatal=False)
                )
    except WebSocketDisconnect:
        # Reconnect / mid-game seat cleanup arrives in V4 (resilience).
        pass
    finally:
        # Drop this session unless a newer one already replaced it (newest-wins).
        registry.remove_if_current(session)
