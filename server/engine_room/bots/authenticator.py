"""Bot API-key authentication — the WS-handshake seam (ADR-0014).

The bot WebSocket endpoint (sub-step 5) resolves a presented `Authorization:
Bearer <key>` to a real Bot identity through this interface. It is injected via
`create_app(...)`/`app.state` exactly like the finalizer (D-c), so WS-seam unit
tests can supply an in-memory `FakeBotAuthenticator` and stay DB-free, while
production wires the Postgres-backed one.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select

from ..persistence.db import SessionLocal
from ..persistence.models import Bot
from ..protocol.messages import BotInfo
from .keys import hash_key


class BotAuthenticator(Protocol):
    async def authenticate(self, bearer_key: str) -> BotInfo | None:
        """Return the Bot identity for a valid key, else None."""
        ...


class NullAuthenticator:
    """Rejects every key. The safe default when `create_app` is called without an
    authenticator (no accidental auth bypass); production injects the Postgres one
    and WS tests inject an in-memory fake."""

    async def authenticate(self, bearer_key: str) -> BotInfo | None:
        return None


class PostgresBotAuthenticator:
    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

    async def authenticate(self, bearer_key: str) -> BotInfo | None:
        if not bearer_key:
            return None
        key_hash = hash_key(bearer_key)
        async with self._session_factory() as session:
            bot = await session.scalar(select(Bot).where(Bot.key_hash == key_hash))
        if bot is None:
            return None
        return BotInfo(id=bot.id, name=bot.name, rating=bot.rating)
