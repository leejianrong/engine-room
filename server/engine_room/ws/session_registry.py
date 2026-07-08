"""Live-session registry — one live Session per Bot, newest-wins (ADR-0016 A6).

Single-process, in-memory (MVP scope, R5). When a bot opens a second
authenticated connection, the new Session replaces the old and the endpoint
closes the stale socket — this is what makes reconnect-over-a-half-dead-socket
work. Key rotation also evicts the live session (ADR-0014).

Game-seat *reconnect/resume* (rebinding a mid-game seat to the new session via
`welcome.active_game`) is V4 (D-h); V2 only proves session replacement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import Session


class SessionRegistry:
    def __init__(self) -> None:
        self._by_bot: dict[str, Session] = {}

    def register(self, session: Session) -> Session | None:
        """Make `session` the live session for its bot; return the session it
        replaced (to be closed by the caller), or None."""
        bot_id = session.bot.id
        prev = self._by_bot.get(bot_id)
        self._by_bot[bot_id] = session
        return prev if prev is not session else None

    def evict(self, bot_id: str) -> Session | None:
        """Remove and return the live session for a bot (used by key rotation)."""
        return self._by_bot.pop(bot_id, None)

    def current(self, bot_id: str) -> Session | None:
        return self._by_bot.get(bot_id)

    def remove_if_current(self, session: Session) -> None:
        """Drop `session` on disconnect — but only if it is still the live one, so
        a newer replacement session is never evicted by the old one's cleanup."""
        if self._by_bot.get(session.bot.id) is session:
            del self._by_bot[session.bot.id]
