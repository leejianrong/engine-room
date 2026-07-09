"""A Session is one live authenticated bot WebSocket connection (glossary; ADR-0009).

A Session wraps the socket and serializes outbound frames so concurrent senders
(the game loop, the heartbeat task) never interleave writes. It is pure
*transport*: in V4 the durable inbound move queue lives on the seat, not here, so
a newest-wins reconnect can swap the session under a running game without losing
in-flight moves (D-i). `last_pong` records the last heartbeat reply (§10).
"""

import asyncio
import contextlib

from fastapi import WebSocket
from pydantic import BaseModel

from ..protocol.messages import BotInfo, Error

# App-defined WS close code: this session was superseded (newest-wins / rotation).
CLOSE_SESSION_REPLACED = 4001


class Session:
    def __init__(self, websocket: WebSocket, bot: BotInfo, session_id: str):
        self.ws = websocket
        self.bot = bot
        self.session_id = session_id
        self._send_lock = asyncio.Lock()
        # Last time a heartbeat `pong` was seen (monotonic seconds); set by the
        # endpoint's receive loop, read by the ping task for liveness (V4 s5).
        self.last_pong: float = 0.0

    async def send(self, message: BaseModel) -> None:
        """Serialize and send one outbound message as a JSON text frame."""
        async with self._send_lock:
            await self.ws.send_text(message.model_dump_json())

    async def terminate(
        self, message: str, code: str = "SESSION_REPLACED"
    ) -> None:
        """Best-effort: tell the peer why, then close the socket. Used for
        newest-wins replacement (ADR-0016 A6) and key rotation (ADR-0014). The
        old socket may already be half-dead, so both steps are suppressed."""
        with contextlib.suppress(Exception):
            await self.send(Error(code=code, message=message, fatal=True))
        with contextlib.suppress(Exception):
            await self.ws.close(CLOSE_SESSION_REPLACED)
