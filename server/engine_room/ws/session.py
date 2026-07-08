"""A Session is one live authenticated bot WebSocket connection (glossary; ADR-0009).

Seat/game binding and reconnect (newest-wins) arrive with real auth in V2 and
resilience in V4. For now a Session wraps the socket and serializes outbound
frames so concurrent senders (later: the game loop) never interleave writes.
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
        # In-game messages (move, ...) the endpoint routes here for the game loop
        # to consume, so the socket has a single reader (the endpoint).
        self.inbound: asyncio.Queue = asyncio.Queue()

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
