"""KAN-51 (integration, real Postgres): the public leaderboard ranks bots by
rating (descending), honours the limit, and excludes never-played bots.

Read-only over the `bots` table — this seeds a few bot rows and asserts the
ordering/limit of GET /api/leaderboard. Binds the app's request-scoped session to
the ephemeral testcontainer via `get_async_session`, mirroring conftest's `app`.
"""

from datetime import datetime, timezone

import httpx

from engine_room.app import create_app
from engine_room.persistence.db import get_async_session
from engine_room.persistence.models import Bot


async def _insert_bot(
    session_factory, bot_id, name, rating, games_played, is_house=False
):
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Bot(
                    id=bot_id,
                    owner_id=None,
                    name=name,
                    rating=rating,
                    games_played=games_played,
                    is_house=is_house,
                    created_at=datetime.now(timezone.utc),
                )
            )


def _app(session_factory):
    application = create_app()

    async def _override_session():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_async_session] = _override_session
    return application


async def test_leaderboard_ranks_by_rating_desc(session_factory):
    await _insert_bot(session_factory, "bot_a", "alice", 1300, 10)
    await _insert_bot(session_factory, "bot_b", "bob", 1500, 5, is_house=True)
    await _insert_bot(session_factory, "bot_c", "carol", 1100, 3)
    # Never played → excluded from the ranking.
    await _insert_bot(session_factory, "bot_d", "dave", 1900, 0)

    app = _app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/leaderboard")

    assert resp.status_code == 200
    entries = resp.json()["entries"]

    assert [e["name"] for e in entries] == ["bob", "alice", "carol"]
    assert [e["rank"] for e in entries] == [1, 2, 3]
    top = entries[0]
    assert top["bot_id"] == "bot_b"
    assert top["rating"] == 1500
    assert top["games_played"] == 5
    assert top["is_house"] is True
    assert all(e["name"] != "dave" for e in entries)  # 0-game bot excluded


async def test_leaderboard_honours_limit(session_factory):
    for i in range(5):
        await _insert_bot(session_factory, f"bot_{i}", f"b{i}", 1200 + i, 1)

    app = _app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/leaderboard?limit=2")

    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 2
    # Highest-rated two, in order.
    assert [e["name"] for e in entries] == ["b4", "b3"]


async def test_leaderboard_rejects_bad_limit(session_factory):
    app = _app(session_factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        assert (await client.get("/api/leaderboard?limit=0")).status_code == 422
        assert (await client.get("/api/leaderboard?limit=99999")).status_code == 422
