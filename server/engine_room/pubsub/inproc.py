"""In-process pub/sub (no Redis at MVP, ADR-0025). Single-process fan-out."""

from __future__ import annotations

import asyncio
from collections import defaultdict


class InProcSubscription:
    def __init__(self, pubsub: "InProcPubSub", channel: str):
        self._pubsub = pubsub
        self._channel = channel
        self._queue: asyncio.Queue = asyncio.Queue()

    async def get(self) -> dict:
        return await self._queue.get()

    def deliver(self, event: dict) -> None:
        self._queue.put_nowait(event)

    def close(self) -> None:
        self._pubsub._remove(self._channel, self)


class InProcPubSub:
    def __init__(self) -> None:
        self._subs: dict[str, set[InProcSubscription]] = defaultdict(set)

    def subscribe(self, channel: str) -> InProcSubscription:
        sub = InProcSubscription(self, channel)
        self._subs[channel].add(sub)
        return sub

    async def publish(self, channel: str, event: dict) -> None:
        for sub in list(self._subs.get(channel, ())):
            sub.deliver(event)

    def _remove(self, channel: str, sub: InProcSubscription) -> None:
        subs = self._subs.get(channel)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                self._subs.pop(channel, None)
