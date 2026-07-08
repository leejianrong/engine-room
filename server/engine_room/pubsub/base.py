"""PubSub interface (R6, ADR-0015/0020).

The bot-event bus and the spectator fan-out bus are the same abstraction; at
MVP it is in-process (inproc.py), and a Redis-backed impl swaps in at
multi-worker scale-out without touching callers.

`subscribe` is synchronous and returns immediately-registered `Subscription`,
so a caller (the SSE endpoint) can guarantee it is subscribed before any events
are published — avoiding a lost-first-event race.
"""

from __future__ import annotations

from typing import Protocol


class Subscription(Protocol):
    async def get(self) -> dict:
        """Await the next event on this subscription's channel."""
        ...

    def close(self) -> None:
        """Unsubscribe. Safe to call more than once."""
        ...


class PubSub(Protocol):
    def subscribe(self, channel: str) -> Subscription:
        ...

    async def publish(self, channel: str, event: dict) -> None:
        ...
