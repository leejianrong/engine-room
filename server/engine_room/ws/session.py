"""A Session is one live authenticated bot WebSocket connection (glossary; ADR-0009).

Seat/game binding and reconnect (newest-wins) arrive with real auth in V2 and
resilience in V4. For now a Session wraps the socket and serializes outbound
frames so concurrent senders (later: the game loop) never interleave writes.
"""

import asyncio

from fastapi import WebSocket
from pydantic import BaseModel

from ..protocol.messages import BotInfo


class Session:
    def __init__(self, websocket: WebSocket, bot: BotInfo, session_id: str):
        self.ws = websocket
        self.bot = bot
        self.session_id = session_id
        self._send_lock = asyncio.Lock()

    async def send(self, message: BaseModel) -> None:
        """Serialize and send one outbound message as a JSON text frame."""
        async with self._send_lock:
            await self.ws.send_text(message.model_dump_json())
