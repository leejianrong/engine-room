"""The bot WebSocket endpoint — PROTOCOL.md §3-5 (handshake + seek) + §8 reconnect.

Handshake authenticates the bot's real API key (ADR-0014; injected
`BotAuthenticator`), binds the Session to the real Bot identity, and enforces
newest-wins session replacement (ADR-0016 A6). `hello`->`welcome`,
protocol-version check, and `seek`->`seek_ack`/pairing follow.

Reconnect-resume (V4, PROTOCOL §8): on reconnect the bot re-opens the socket and
sends `hello`; if it has a live game, `welcome.active_game` carries the resume
snapshot, its seat is rebound to the new session, and a `your_turn` is re-sent if
it is the bot's turn. The clock keeps running while away (ADR-0025 #3 — no
separate reconnect window). If the game ended while the bot was away, the missed
`game_over` is delivered on reconnect (D-vi).
"""

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ids import new_id
from ..protocol.messages import (
    DrawAccept,
    DrawOffer,
    Error,
    GameOver,
    Hello,
    Move,
    Ping,
    Pong,
    ProtocolError,
    Rating,
    Resign,
    Seek,
    SeekAck,
    SeekCancel,
    Welcome,
    parse_client_message,
)
from .session import Session

if TYPE_CHECKING:
    from ..game.game import Game
    from .session_registry import SessionRegistry

router = APIRouter()

SERVER_PROTOCOL_VERSION = "1.0"
SUPPORTED_VERSIONS = {"1.0"}

# WebSocket close codes
_CLOSE_POLICY_VIOLATION = 1008
_CLOSE_PROTOCOL_ERROR = 1002


async def _heartbeat(session: Session, ping_interval: float, liveness_timeout: float) -> None:
    """Ping this socket on an interval; if no `pong` arrives within the liveness
    window, close it — turning a half-dead socket into a real disconnect (§10).
    Used only so mutual abandonment can be detected; a lone bot is never forfeited
    here (its clock governs, ADR-0025 #3)."""
    while True:
        await asyncio.sleep(ping_interval)
        if time.monotonic() - session.last_pong > liveness_timeout:
            with contextlib.suppress(Exception):
                await session.ws.close()
            return
        with contextlib.suppress(Exception):
            await session.send(Ping(t=int(time.monotonic() * 1000)))


def _mutually_abandoned(game: "Game", session_registry: "SessionRegistry") -> bool:
    """True only if EVERY seat is a real bot AND none has a live session (I7). A
    house seat is always present, so a house game is never mutually abandoned."""
    for participant in (game.white, game.black):
        if participant.is_house:
            return False
        if session_registry.current(participant.bot.id) is not None:
            return False
    return True


def _terminal_game_over(game: "Game", bot) -> GameOver:
    """Rebuild the game_over a bot missed while disconnected (D-vi). An aborted
    game carries no rating (§8 — ABORTED does not affect rating)."""
    rating = None if game.result == "aborted" else Rating(before=bot.rating, after=bot.rating)
    return GameOver(
        game_id=game.id,
        result=game.result,
        termination=game.termination,
        final_fen=game.final_fen,
        pgn=game.pgn or "",
        rating=rating,
    )


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

    # --- newest-wins: this becomes the bot's live session; close the prior one
    # FIRST (ADR-0016 A6) so the welcome/resume below goes out on the new socket
    # only. Best-effort — the old socket may already be half-dead. ---
    registry = websocket.app.state.session_registry
    game_registry = websocket.app.state.game_registry
    replaced = registry.register(session)
    if replaced is not None:
        await replaced.terminate("replaced by a newer connection")

    # --- reconnect-resume (PROTOCOL §8): rebind a live game seat to this session
    # and hand back the resume snapshot; the clock kept running while away. ---
    active = game_registry.active_game_for(session.bot.id)
    resume = active.resume_payload(session.bot.id) if active is not None else None

    await session.send(
        Welcome(
            protocol_version=SERVER_PROTOCOL_VERSION,
            session_id=session.session_id,
            bot=session.bot,
            active_game=resume,
        )
    )

    if active is not None and resume is not None:
        seat = active.seat_for(session.bot.id)
        if seat is not None:
            seat.rebind(session)  # outbound now targets the new socket
            # Its your_turn (if any) went to the dead socket — re-send if on move.
            if resume["to_move"] == resume["your_color"]:
                await seat.resend_your_turn(active.live)
    elif active is None:
        # The bot's game ended while it was away → deliver the missed game_over.
        terminal = game_registry.recent_terminal_for(session.bot.id)
        if terminal is not None:
            await session.send(_terminal_game_over(terminal, session.bot))
            game_registry.clear_recent_terminal(session.bot.id)

    # --- heartbeat: ping this socket on an interval; a missed liveness window
    # closes it so a half-dead socket becomes a real disconnect (§10). ---
    session.last_pong = time.monotonic()
    hb_task = asyncio.create_task(
        _heartbeat(
            session,
            websocket.app.state.hb_ping_interval_seconds,
            websocket.app.state.hb_liveness_timeout_seconds,
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
                result = await queue.seek(
                    session, msg.time_control, opponent_bot_id=msg.opponent_bot_id
                )
                if result.error is not None:
                    # A rejected direct challenge (KAN-55): report and keep the
                    # connection open so the bot can seek again (non-fatal).
                    await session.send(
                        Error(code=result.error.code, message=result.error.message)
                    )
                    continue
                await session.send(
                    SeekAck(id=msg.id, seek_id=result.seek_id, status=result.status)
                )
                # Async matcher path (V3): game_start arrives later, via the
                # launcher. The always-pair and direct-challenge (KAN-55) paths
                # return an inline game whose launch we drive here.
                if result.game is not None:
                    await websocket.app.state.game_launcher.launch(result.game)
            elif isinstance(msg, SeekCancel):
                # Withdraw a waiting seek (ADR-0016 E8); matcher → seek_ended.
                await queue.cancel(msg.seek_id)
            elif isinstance(msg, Move):
                # Single socket reader: route in-game moves to the bot's live
                # seat inbox (durable across reconnects, V4 D-i) via the
                # active-game index. No game → NO_ACTIVE_GAME (§11).
                active = game_registry.active_game_for(session.bot.id)
                seat = active.seat_for(session.bot.id) if active is not None else None
                if seat is None:
                    await session.send(
                        Error(code="NO_ACTIVE_GAME", message="no active game for this move")
                    )
                else:
                    await seat.inbound.put(msg)
            elif isinstance(msg, (Resign, DrawOffer, DrawAccept)):
                # Control frames (§7) can arrive when it is NOT this bot's turn, so
                # they go to the game-level control channel the loop always watches
                # (not the move-only seat inbox) — tagged with the sender's color.
                active = game_registry.active_game_for(session.bot.id)
                color = active.color_of(session.bot.id) if active is not None else None
                if color is None:
                    await session.send(
                        Error(code="NO_ACTIVE_GAME", message="no active game for this control")
                    )
                else:
                    await active.controls.put((color, msg))
            elif isinstance(msg, Pong):
                # Heartbeat reply (§10): the socket is alive.
                session.last_pong = time.monotonic()
            elif isinstance(msg, Hello):
                await session.send(
                    Error(code="INVALID_MESSAGE", message="already handshaken", fatal=False)
                )
            else:  # pragma: no cover - no other client models yet
                await session.send(
                    Error(code="INVALID_MESSAGE", message="unhandled type", fatal=False)
                )
    except WebSocketDisconnect:
        # A drop mid-game is fine: the seat's inbox is durable and the clock keeps
        # running (ADR-0025 #3). The bot reconnects, flags, or — if its opponent
        # is also gone — the game aborts (below).
        pass
    finally:
        hb_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb_task
        # Drop this session unless a newer one already replaced it (newest-wins).
        registry.remove_if_current(session)
        # Mutual abandonment (§10 / I7): if this bot truly dropped (not replaced)
        # while in a live game and its opponent is also gone, abort the game — no
        # result, no rating. A single drop is NOT aborted (the clock governs).
        if registry.current(session.bot.id) is None:
            active = game_registry.active_game_for(session.bot.id)
            if (
                active is not None
                and active.state == "in_progress"
                and _mutually_abandoned(active, registry)
            ):
                active.abort.set()
