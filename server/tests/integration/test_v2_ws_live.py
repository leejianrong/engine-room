"""Sub-step 5 checkpoint (end-to-end, real uvicorn + real websockets):

1. Newest-wins — a second authenticated connection for a bot closes the first
   socket with a SESSION_REPLACED error (ADR-0016 A6). Uses a fake authenticator
   (no DB).
2. A real DB-issued API key authenticates the WS handshake and binds the real
   Bot identity, via PostgresBotAuthenticator (needs Docker).

Real websockets (not the sync TestClient) so cross-socket close and cross-loop
DB access behave like production.
"""

import asyncio
import contextlib
import json
import threading

import pytest
import uvicorn
import websockets
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from support.fake_client import FakeBotAuthenticator

from engine_room.app import create_app
from engine_room.protocol.messages import BotInfo

WS_PATH = "/api/bot/v1"


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # off the main thread → no signals
        pass


@contextlib.asynccontextmanager
async def live_server(authenticator):
    app = create_app(bot_authenticator=authenticator)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = _Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _connect(hostport: str, key: str):
    return websockets.connect(
        f"ws://{hostport}{WS_PATH}",
        additional_headers={"Authorization": f"Bearer {key}"},
    )


async def _hello(ws) -> dict:
    await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
    return json.loads(await ws.recv())


async def test_newest_wins_closes_prior_socket():
    key = "crbk_dup"
    authn = FakeBotAuthenticator({key: BotInfo(id="bot_dup", name="d", rating=1200)})
    async with live_server(authn) as hostport:
        ws1 = await _connect(hostport, key)
        w1 = await _hello(ws1)
        assert w1["bot"]["id"] == "bot_dup"

        ws2 = await _connect(hostport, key)
        w2 = await _hello(ws2)
        assert w2["type"] == "welcome"

        # The prior socket is told it was replaced, then closed.
        frame = json.loads(await asyncio.wait_for(ws1.recv(), timeout=5))
        assert frame["type"] == "error"
        assert frame["code"] == "SESSION_REPLACED"
        with pytest.raises(websockets.ConnectionClosed):
            await asyncio.wait_for(ws1.recv(), timeout=5)

        await ws2.close()


async def test_real_db_key_authenticates_handshake(session_factory, _postgres_url):
    from engine_room.bots.authenticator import PostgresBotAuthenticator
    from engine_room.bots.schemas import BotCreate
    from engine_room.bots.service import create_bot
    from engine_room.persistence.models import User

    # Provision a user + bot (with a key) directly in the container.
    async with session_factory() as session:
        user = User(
            email="db@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        bot, api_key = await create_bot(session, user.id, BotCreate(name="db-bot"))
        bot_id = bot.id

    # The live server authenticates against the same DB via its own (NullPool)
    # engine, so connections are opened/closed on the server's loop only.
    async_url = _postgres_url.replace("+psycopg", "+asyncpg")
    auth_engine = create_async_engine(async_url, poolclass=NullPool)
    authn = PostgresBotAuthenticator(
        session_factory=async_sessionmaker(auth_engine, expire_on_commit=False)
    )
    try:
        async with live_server(authn) as hostport:
            async with _connect(hostport, api_key) as ws:
                welcome = await _hello(ws)
        assert welcome["bot"]["id"] == bot_id
        assert welcome["bot"]["name"] == "db-bot"
        assert welcome["bot"]["rating"] == 1200
    finally:
        await auth_engine.dispose()
