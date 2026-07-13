"""Redis-backed pub/sub (KAN-62) — cross-worker spectator SSE fan-out.

Mirrors `InProcPubSub`'s contract (`base.py`) but fans events out across worker
*processes* via Redis pub/sub, so a spectator SSE stream served by one uvicorn
worker sees the game events published by whichever worker runs that game's loop.
Config-gated: the app only uses this when `ER_REDIS_URL` is set — otherwise the
in-process bus is used and dev/CI/prod behaviour is unchanged (see `app.py`).

The sync-`subscribe()` / no-lost-event contract
------------------------------------------------
`base.PubSub.subscribe` is synchronous and must return an already-registered
`Subscription` (Redis SUBSCRIBE is async). We satisfy this the same way the
in-process bus does — with a LOCAL per-channel registry (`_subs`) — plus a single
connection that pattern-subscribes ONCE to the whole event namespace at startup:

  * `start()` opens one Redis connection and `PSUBSCRIBE`s `game:*` (awaited, so on
    return the subscription is confirmed by the broker), then spawns one background
    reader task that reads every matching message and dispatches it to `_subs`.
  * `subscribe(channel)` stays synchronous — it only adds a `RedisSubscription` to
    the local registry. Because the worker is ALREADY receiving every `game:*`
    channel, nothing published after `subscribe()` returns is lost between then and
    the first `get()`: the reader delivers it into the subscription's queue.

This preserves the SSE endpoint's guarantee (`sse.py`): it subscribes before it
reads the catch-up snapshot, and any event published in that gap is queued in the
tail — now true across workers too.

`subscriber_count()` in this slice
-----------------------------------
`subscriber_count(channel)` backs the KAN-54 lobby spectator count. With a single
pattern-subscribe, Redis `PUBSUB NUMSUB` does NOT reflect it, and a correct
CROSS-WORKER count needs shared state (e.g. a Redis counter per channel,
INCR/DECR on subscribe/close with a TTL to survive crashes). This slice keeps it a
PER-WORKER LOCAL count (this worker's live subscriptions on the channel) — honest
and cheap; the lobby count may under-report when spectators are spread across
workers. A correct cross-worker count is a documented follow-up (see the PR).

Connection loss
---------------
The reader task tolerates a dropped Redis connection: it logs a warning and
reconnects (re-`PSUBSCRIBE`) with a short backoff, rather than dying silently.
Events published while disconnected are lost (Redis pub/sub is fire-and-forget,
at-most-once) — acceptable for a live spectator tail, which self-heals on the next
event and via the SSE catch-up snapshot on reconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# The whole event namespace (see `channels.game_channel` → "game:<id>"). One
# pattern-subscribe here covers every game channel this worker might stream.
EVENT_PATTERN = "game:*"


class RedisSubscription:
    """A single spectator subscription. Identical shape to `InProcSubscription`:
    events are delivered into a local queue by the shared reader task."""

    def __init__(self, pubsub: "RedisPubSub", channel: str):
        self._pubsub = pubsub
        self._channel = channel
        self._queue: asyncio.Queue = asyncio.Queue()

    async def get(self) -> dict:
        return await self._queue.get()

    def deliver(self, event: dict) -> None:
        self._queue.put_nowait(event)

    def close(self) -> None:
        self._pubsub._remove(self._channel, self)


class RedisPubSub:
    """Cross-worker `PubSub` over `redis.asyncio`. See the module docstring."""

    def __init__(self, url: str, *, reconnect_delay_seconds: float = 1.0) -> None:
        self._url = url
        self._reconnect_delay = reconnect_delay_seconds
        self._subs: dict[str, set[RedisSubscription]] = {}
        self._redis: Redis | None = None
        self._pubsub = None
        self._reader: asyncio.Task | None = None
        self._closing = False

    # --- lifecycle (wired into the app lifespan, like the matchmaking queue) ---

    async def start(self) -> None:
        """Open the shared connection and pattern-subscribe BEFORE returning, then
        spawn the background reader. Awaiting the PSUBSCRIBE guarantees the broker
        has registered us before any caller subscribes/publishes."""
        self._closing = False
        # decode_responses so channel/data arrive as str (we JSON-decode the data).
        self._redis = Redis.from_url(self._url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(EVENT_PATTERN)
        self._reader = asyncio.create_task(self._read_loop(), name="redis-pubsub-reader")

    async def stop(self) -> None:
        """Cancel the reader and close the connection cleanly."""
        self._closing = True
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
            self._reader = None
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()
            except Exception:  # pragma: no cover - best-effort close
                logger.debug("redis pubsub close failed", exc_info=True)
            self._pubsub = None
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # pragma: no cover - best-effort close
                logger.debug("redis client close failed", exc_info=True)
            self._redis = None

    # --- PubSub protocol ------------------------------------------------------

    def subscribe(self, channel: str) -> RedisSubscription:
        sub = RedisSubscription(self, channel)
        self._subs.setdefault(channel, set()).add(sub)
        return sub

    async def publish(self, channel: str, event: dict) -> None:
        if self._redis is None:
            raise RuntimeError("RedisPubSub.publish() before start()")
        await self._redis.publish(channel, json.dumps(event))

    def subscriber_count(self, channel: str) -> int:
        """PER-WORKER live subscriber count for `channel` (this slice; see the
        module docstring for the cross-worker follow-up)."""
        return len(self._subs.get(channel, ()))

    # --- internals ------------------------------------------------------------

    def _remove(self, channel: str, sub: RedisSubscription) -> None:
        subs = self._subs.get(channel)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                self._subs.pop(channel, None)

    def _dispatch(self, message: dict) -> None:
        channel = message.get("channel")
        try:
            event = json.loads(message["data"])
        except (KeyError, TypeError, ValueError):
            logger.warning("dropping non-JSON redis pubsub message on %r", channel)
            return
        for sub in list(self._subs.get(channel, ())):
            sub.deliver(event)

    async def _read_loop(self) -> None:
        """Read every matching Redis message and fan it out to local subscribers.
        Reconnects on connection loss; exits on cancellation."""
        while not self._closing:
            try:
                async for message in self._pubsub.listen():
                    if message and message.get("type") == "pmessage":
                        self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._closing:
                    break
                logger.warning(
                    "redis pubsub reader lost its connection; reconnecting", exc_info=True
                )
                await self._reconnect()

    async def _reconnect(self) -> None:
        """Re-establish the pattern subscription after a connection drop."""
        while not self._closing:
            await asyncio.sleep(self._reconnect_delay)
            try:
                self._pubsub = self._redis.pubsub()
                await self._pubsub.psubscribe(EVENT_PATTERN)
                logger.info("redis pubsub reader reconnected")
                return
            except Exception:  # pragma: no cover - retried until it works
                logger.warning("redis pubsub reconnect failed; retrying", exc_info=True)
