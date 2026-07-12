"""Unit tests for the in-process pub/sub fan-out."""

import asyncio

import pytest

from engine_room.pubsub.inproc import InProcPubSub


async def test_fanout_to_multiple_subscribers():
    ps = InProcPubSub()
    a = ps.subscribe("chan")
    b = ps.subscribe("chan")

    await ps.publish("chan", {"n": 1})

    assert (await a.get())["n"] == 1
    assert (await b.get())["n"] == 1


async def test_unsubscribe_stops_delivery():
    ps = InProcPubSub()
    a = ps.subscribe("chan")
    b = ps.subscribe("chan")

    a.close()
    await ps.publish("chan", {"n": 2})

    assert (await b.get())["n"] == 2
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(a.get(), timeout=0.05)


async def test_publish_with_no_subscribers_is_a_noop():
    ps = InProcPubSub()
    sub = ps.subscribe("chan")
    sub.close()
    # channel now has no subscribers; publishing must not raise
    await ps.publish("chan", {"n": 3})


async def test_subscriber_count_tracks_live_subscriptions():
    ps = InProcPubSub()
    assert ps.subscriber_count("chan") == 0
    a = ps.subscribe("chan")
    b = ps.subscribe("chan")
    assert ps.subscriber_count("chan") == 2
    assert ps.subscriber_count("other") == 0
    a.close()
    assert ps.subscriber_count("chan") == 1
    b.close()
    assert ps.subscriber_count("chan") == 0


async def test_channels_are_isolated():
    ps = InProcPubSub()
    a = ps.subscribe("a")
    b = ps.subscribe("b")

    await ps.publish("a", {"n": 1})

    assert (await a.get())["n"] == 1
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(b.get(), timeout=0.05)
