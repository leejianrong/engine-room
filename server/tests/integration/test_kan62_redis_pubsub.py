"""KAN-62: Redis-backed pub/sub fans spectator SSE events across workers.

Two `RedisPubSub` instances against the SAME Redis container each stand in for a
separate uvicorn worker. Instance A publishes; instance B (which only ever
subscribed locally) must receive — proving the fan-out crosses processes, not just
in-memory queues. Deterministic: every read is an `asyncio.wait_for` on the
subscription queue (no sleep-and-hope), and each instance's `start()` awaits its
PSUBSCRIBE so it is guaranteed subscribed before anything is published.

Needs Docker (testcontainers Redis); skipped where Docker is unavailable, like the
Postgres integration tests.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from engine_room.pubsub.redis import RedisPubSub

# A short but generous ceiling: delivery is effectively immediate, so a passing
# test never waits this long; a broken fan-out fails fast instead of hanging.
_DELIVERY_TIMEOUT = 3.0


async def _next(sub, timeout: float = _DELIVERY_TIMEOUT) -> dict:
    return await asyncio.wait_for(sub.get(), timeout=timeout)


@pytest_asyncio.fixture
async def worker_a(redis_url):
    bus = RedisPubSub(redis_url)
    await bus.start()
    try:
        yield bus
    finally:
        await bus.stop()


@pytest_asyncio.fixture
async def worker_b(redis_url):
    bus = RedisPubSub(redis_url)
    await bus.start()
    try:
        yield bus
    finally:
        await bus.stop()


async def test_fan_out_crosses_workers(worker_a, worker_b):
    """Subscribe on B, publish on A → B receives (cross-worker fan-out)."""
    sub = worker_b.subscribe("game:g1")
    await worker_a.publish("game:g1", {"type": "move", "ply": 1, "san": "e4"})

    event = await _next(sub)
    assert event == {"type": "move", "ply": 1, "san": "e4"}


async def test_multiple_subscribers_same_channel_all_receive(worker_a, worker_b):
    """Two subscribers on the same channel both get every event."""
    s1 = worker_b.subscribe("game:g2")
    s2 = worker_b.subscribe("game:g2")
    await worker_a.publish("game:g2", {"type": "move", "ply": 1})

    assert await _next(s1) == {"type": "move", "ply": 1}
    assert await _next(s2) == {"type": "move", "ply": 1}


async def test_close_stops_delivery(worker_a, worker_b):
    """A closed subscription receives nothing further; a live sibling still does."""
    closing = worker_b.subscribe("game:g3")
    staying = worker_b.subscribe("game:g3")
    closing.close()

    await worker_a.publish("game:g3", {"type": "move", "ply": 1})

    # The surviving subscription gets it...
    assert await _next(staying) == {"type": "move", "ply": 1}
    # ...and the closed one never does.
    with pytest.raises(asyncio.TimeoutError):
        await _next(closing, timeout=0.5)


async def test_channels_are_isolated(worker_a, worker_b):
    """An event on one channel is not delivered to another channel's subscriber."""
    other = worker_b.subscribe("game:other")
    await worker_a.publish("game:g4", {"type": "move", "ply": 1})

    with pytest.raises(asyncio.TimeoutError):
        await _next(other, timeout=0.5)


async def test_subscriber_count_is_local_per_worker(worker_a, worker_b):
    """subscriber_count is a per-worker local count in this slice: it reflects THIS
    instance's subscriptions, not the cross-worker total (documented follow-up)."""
    worker_b.subscribe("game:g5")
    worker_b.subscribe("game:g5")

    assert worker_b.subscriber_count("game:g5") == 2
    # A's PSUBSCRIBE is a single pattern subscription, not per-channel state — so it
    # reports 0 local subscribers on that channel.
    assert worker_a.subscriber_count("game:g5") == 0
