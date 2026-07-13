"""KAN-56 round-robin tournaments (end-to-end, real uvicorn + real websockets + DB):

- **enrollment validation** — a tournament-tagged `seek` enrolls (seek_ack
  status "enrolled"); a second enroll from the same bot → error {INVALID_TOURNAMENT}
  "already entered"; an unknown tournament → error "no such tournament".
- **the full loop** — create a 3-bot round-robin over REST → three bots opt in via
  seek → the field fills, the schedule auto-runs its games over the normal game
  launcher → standings persist and `GET /api/tournaments/{id}` returns them sorted.

Real websockets (not the sync TestClient) so the three bots can be driven
concurrently on the server's own loop; the DB is the ephemeral testcontainers
Postgres, wired NullPool so the live server touches it from its own loop (mirrors
test_v7_sdk_live). Needs Docker.
"""

import asyncio
import contextlib
import json
import random
import threading
from datetime import datetime, timezone

import chess
import httpx
import uvicorn
import websockets
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from support.fake_client import FakeBotAuthenticator
from testcontainers.postgres import PostgresContainer

from engine_room.app import create_app
from engine_room.auth.deps import current_active_user
from engine_room.persistence.db import get_async_session
from engine_room.persistence.finalize import PostgresFinalizer
from engine_room.persistence.models import Base, Bot, User
from engine_room.persistence.models import Game as GameRow
from engine_room.protocol.messages import BotInfo

WS_PATH = "/api/bot/v1"
_BOT_IDS = ["bot_t0", "bot_t1", "bot_t2"]


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # off the main thread → no signals
        pass


def _authenticator() -> FakeBotAuthenticator:
    return FakeBotAuthenticator(
        {f"crbk_{i}": BotInfo(id=bid, name=bid, rating=1200, owner_id="u1")
         for i, bid in enumerate(_BOT_IDS)}
    )


async def _seed(session_factory):
    """A creating user + the three tournament bots (entry/game FKs resolve)."""
    async with session_factory() as session:
        user = User(email="tour@example.com", hashed_password="x", is_active=True,
                    is_superuser=False, is_verified=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        for bid in _BOT_IDS:
            session.add(Bot(id=bid, owner_id=user.id, name=bid, description="",
                            rating=1200, is_house=False, created_at=datetime.now(timezone.utc)))
        await session.commit()
        return user


@contextlib.asynccontextmanager
async def _live_server(factory, user):
    app = create_app(
        bot_authenticator=_authenticator(),
        finalizer=PostgresFinalizer(session_factory=factory),
        tournament_session_factory=factory,
        matcher_kwargs={"greeter_pools": (), "tick_interval_seconds": 5.0},
    )

    async def _override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override_session
    app.dependency_overrides[current_active_user] = lambda: user

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = _Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        yield f"127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _connect(hostport, key):
    return websockets.connect(
        f"ws://{hostport}{WS_PATH}",
        additional_headers={"Authorization": f"Bearer {key}"},
    )


async def _hello(ws) -> None:
    await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
    await ws.recv()  # welcome


async def _enroll(ws, tournament_id, *, cid="c1") -> dict:
    await ws.send(json.dumps({
        "type": "seek", "id": cid, "tournament_id": tournament_id,
        "time_control": {"base_seconds": 180, "increment_seconds": 0},
    }))
    return json.loads(await ws.recv())  # seek_ack or error


async def _drive(ws, stop: asyncio.Event) -> None:
    """Auto-play: respond to each your_turn with a random legal move; pong pings."""
    rng = random.Random(hash(ws) & 0xFFFF)
    while not stop.is_set():
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        except websockets.ConnectionClosed:
            return
        msg = json.loads(raw)
        t = msg.get("type")
        if t == "your_turn":
            board = chess.Board(msg["fen"])
            move = rng.choice(list(board.legal_moves))
            await ws.send(json.dumps({
                "type": "move", "game_id": msg["game_id"],
                "ply": msg["ply"], "uci": move.uci(),
            }))
        elif t == "ping":
            await ws.send(json.dumps({"type": "pong", "t": msg.get("t", 0)}))
        # game_start / move_ack / game_over / seek_ack / error are ignored here.


async def _create_tournament(http, target_size=3) -> str:
    resp = await http.post("/api/tournaments", json={
        "name": "Test Cup", "target_size": target_size,
        "time_control": {"base_seconds": 180, "increment_seconds": 0},
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_enrollment_validation():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        async_url = pg.get_connection_url().replace("+psycopg", "+asyncpg")
        engine = create_async_engine(async_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            user = await _seed(factory)
            async with _live_server(factory, user) as hp:
                async with httpx.AsyncClient(base_url=f"http://{hp}") as http:
                    tid = await _create_tournament(http, target_size=3)  # stays pending
                async with _connect(hp, "crbk_0") as a:
                    await _hello(a)
                    ok = await _enroll(a, tid)
                    assert ok["type"] == "seek_ack" and ok["status"] == "enrolled"
                    dup = await _enroll(a, tid, cid="c2")
                    assert dup["type"] == "error" and dup["code"] == "INVALID_TOURNAMENT"
                    assert "already" in dup["message"]
                    missing = await _enroll(a, "tour_nope", cid="c3")
                    assert missing["type"] == "error"
                    assert missing["code"] == "INVALID_TOURNAMENT"
        finally:
            await engine.dispose()


async def test_round_robin_runs_and_persists_standings():
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        async_url = pg.get_connection_url().replace("+psycopg", "+asyncpg")
        engine = create_async_engine(async_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            user = await _seed(factory)
            async with _live_server(factory, user) as hp:
                async with httpx.AsyncClient(base_url=f"http://{hp}") as http:
                    tid = await _create_tournament(http, target_size=3)

                stop = asyncio.Event()
                async with _connect(hp, "crbk_0") as a, _connect(hp, "crbk_1") as b, \
                        _connect(hp, "crbk_2") as c:
                    for ws in (a, b, c):
                        await _hello(ws)
                    for i, ws in enumerate((a, b, c)):
                        ack = await _enroll(ws, tid, cid=f"e{i}")
                        assert ack["type"] == "seek_ack" and ack["status"] == "enrolled"

                    drivers = [asyncio.create_task(_drive(ws, stop)) for ws in (a, b, c)]
                    try:
                        detail = await _await_finished(hp, tid, timeout=90)
                    finally:
                        stop.set()
                        for d in drivers:
                            d.cancel()
                        with contextlib.suppress(Exception):
                            await asyncio.gather(*drivers, return_exceptions=True)

            # Standings: 3 entries, 3 real games played, total points == 3.0.
            assert detail["status"] == "finished"
            standings = detail["standings"]
            assert len(standings) == 3
            assert sum(s["score"] for s in standings) == 3.0
            assert [s["rank"] for s in standings] == [1, 2, 3]
            assert standings == sorted(standings, key=lambda s: -s["score"])

            games = detail["games"]
            played = [g for g in games if g["game_id"] is not None]
            byes = [g for g in games if g["result"] == "bye"]
            assert len(played) == 3  # round-robin of 3 → 3 games
            assert len(byes) == 3  # odd field → one bye per round
            assert all(g["result"] in ("white_wins", "black_wins", "draw") for g in played)

            # The linked games are real, persisted rows (finalizer wrote them).
            async with factory() as session:
                for g in played:
                    row = await session.get(GameRow, g["game_id"])
                    assert row is not None and row.result == g["result"]
        finally:
            await engine.dispose()


async def _await_finished(hostport, tid, *, timeout) -> dict:
    async with httpx.AsyncClient(base_url=f"http://{hostport}") as http:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            detail = (await http.get(f"/api/tournaments/{tid}")).json()
            if detail["status"] == "finished":
                return detail
            await asyncio.sleep(0.1)
    raise AssertionError("tournament did not finish in time")
