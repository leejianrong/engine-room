"""V7 sub-step 3 (contract, real uvicorn + real websockets): the *packaged*
engineroom SDK driven against the real server.

This is the honest test of a decoupled client (ADR-0021): the SDK speaks only the
wire protocol, so we run its actual code against a live server rather than mocking
either side. The SDK source is imported from the sibling monorepo package
(`sdk/engineroom`); it is a separate uv project with no `engine_room` dependency
(asserted by the SDK's own boundary test).

- The SDK's RandomBot plays a full greeter game (Kind-2 ephraim-bot) to game_over,
  and appears in the lobby (`GET /api/games`) while it plays. No DB.
- A mid-game socket drop is transparently resumed by the SDK (§8). No DB.
- With a real DB key, the SDK's game is finalized: persisted + rated. Needs Docker.
"""

import asyncio
import contextlib
import pathlib
import sys
import threading

import httpx
import uvicorn
from support.fake_client import FakeBotAuthenticator

from engine_room.app import create_app
from engine_room.config import settings
from engine_room.protocol.messages import BotInfo

# Import the packaged SDK from the monorepo sibling package (V7 Q1: it lives here
# as a decoupled package until it's extracted/published — O-2).
_SDK_SRC = pathlib.Path(__file__).resolve().parents[3] / "sdk" / "engineroom" / "src"
if str(_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(_SDK_SRC))

from engineroom import RandomBot  # noqa: E402
from engineroom.transport import Transport, TransportClosed, WebSocketTransport  # noqa: E402

WS_PATH = "/api/bot/v1"
_GREETER = dict(greeter_solo_wait_seconds=0.0, tick_interval_seconds=0.02)


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # off the main thread → no signals
        pass


@contextlib.asynccontextmanager
async def live_server(*, house_move_delay: float | None = None, **app_kwargs):
    # KAN-83: the on-demand greeter game is launched via the main GameLauncher,
    # whose house move delay comes from `settings.house_move_delay_seconds`
    # (default 0.0 — instant). A RandomBot-vs-RandomBot greeter game with no delay
    # finishes and is evicted from the registry (worker.py) in a fraction of a
    # second, so the lobby's "live" window is a race any poll can lose. A test that
    # asserts the game shows up live pins a small non-zero delay here so the game
    # stays live for seconds — deterministically observable — without touching the
    # production default. Restored on exit.
    prev_delay = settings.house_move_delay_seconds
    if house_move_delay is not None:
        settings.house_move_delay_seconds = house_move_delay
    app = create_app(**app_kwargs)
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
        settings.house_move_delay_seconds = prev_delay


async def _wait_for_lobby_game(hostport: str, name: str, *, timeout: float = 10.0) -> dict:
    """Poll GET /api/games until a live game featuring `name` shows up."""
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(base_url=f"http://{hostport}") as http:
        while asyncio.get_event_loop().time() < deadline:
            resp = await http.get("/api/games")
            for g in resp.json().get("games", []):
                if name in (g["white"]["name"], g["black"]["name"]):
                    return g
            await asyncio.sleep(0.05)
    raise AssertionError(f"{name!r} never appeared in the lobby")


# --------------------------------------------------------------- no-DB contract
async def test_sdk_random_bot_plays_a_greeter_game_and_shows_in_lobby():
    authn = FakeBotAuthenticator(
        {"crbk_sdk": BotInfo(id="bot_sdk", name="sdk-bot", rating=1200, owner_id="u1")}
    )
    # KAN-83: pin a small house move delay so the greeter game stays live for
    # seconds (≫ the 0.05s poll cadence) — the lobby assertion is no longer racing
    # an instant, immediately-evicted game.
    async with live_server(
        bot_authenticator=authn, matcher_kwargs=_GREETER, house_move_delay=0.05
    ) as hp:
        overs: list = []

        class Watched(RandomBot):
            def on_game_over(self, result):
                overs.append(result)

        bot = Watched(key="crbk_sdk", url=f"ws://{hp}{WS_PATH}", seed=7)
        task = asyncio.create_task(bot._run(loop=False))
        try:
            entry = await _wait_for_lobby_game(hp, "sdk-bot", timeout=30.0)
            assert "ephraim-bot" in (entry["white"]["name"], entry["black"]["name"])
            await asyncio.wait_for(task, timeout=60)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        assert len(overs) == 1
        assert overs[0].result in ("white_wins", "black_wins", "draw")


class _DropOnceTransport:
    """Wraps a real transport and forces one disconnect mid-game so the SDK's
    reconnect-resume (§8) is exercised against the real server."""

    def __init__(self, inner: Transport, drop_after: int) -> None:
        self._inner = inner
        self._drop_after = drop_after
        self._reads = 0

    async def send(self, message: dict) -> None:
        await self._inner.send(message)

    async def recv(self) -> dict:
        self._reads += 1
        if self._reads == self._drop_after:
            await self._inner.close()
            raise TransportClosed("simulated mid-game drop")
        return await self._inner.recv()

    async def close(self) -> None:
        await self._inner.close()


async def test_sdk_resumes_after_a_mid_game_drop():
    authn = FakeBotAuthenticator(
        {"crbk_sdk": BotInfo(id="bot_sdk", name="sdk-bot", rating=1200, owner_id="u1")}
    )
    async with live_server(bot_authenticator=authn, matcher_kwargs=_GREETER) as hp:
        url = f"ws://{hp}{WS_PATH}"
        state = {"connections": 0}

        async def connect() -> Transport:
            state["connections"] += 1
            inner = await WebSocketTransport.connect(url, "crbk_sdk")
            if state["connections"] == 1:
                return _DropOnceTransport(inner, drop_after=6)  # drop a few frames in
            return inner

        overs: list = []

        class Watched(RandomBot):
            def on_game_over(self, result):
                overs.append(result)

        bot = Watched(key="crbk_sdk", connect=connect, seed=9)
        await asyncio.wait_for(bot._run(loop=False), timeout=60)

        assert state["connections"] >= 2  # reconnected after the drop
        assert len(overs) == 1  # and still finished the game


# --------------------------------------------------------------- DB contract
async def test_sdk_game_is_persisted_and_rated(session_factory, _postgres_url):
    from sqlalchemy import or_, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from engine_room.bots.authenticator import PostgresBotAuthenticator
    from engine_room.bots.schemas import BotCreate
    from engine_room.bots.service import create_bot
    from engine_room.persistence.finalize import PostgresFinalizer
    from engine_room.persistence.models import Bot as BotRow
    from engine_room.persistence.models import Game as GameRow
    from engine_room.persistence.models import User
    from engine_room.persistence.reader import PostgresGameReader
    from engine_room.persistence.seed import seed_house_bots

    # Provision the house bots (greeter FK) + a real user/bot/key in the container.
    async with session_factory() as session:
        await seed_house_bots(session)
        user = User(email="sdk@example.com", hashed_password="x", is_active=True,
                    is_superuser=False, is_verified=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        bot_row, api_key = await create_bot(session, user.id, BotCreate(name="sdk-live-bot"))
        bot_id = bot_row.id

    # The live server talks to the same DB on its own loop (NullPool).
    async_url = _postgres_url.replace("+psycopg", "+asyncpg")
    engine = create_async_engine(async_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with live_server(
            bot_authenticator=PostgresBotAuthenticator(session_factory=factory),
            finalizer=PostgresFinalizer(session_factory=factory),
            game_reader=PostgresGameReader(session_factory=factory),
            matcher_kwargs=_GREETER,
        ) as hp:
            bot = RandomBot(key=api_key, url=f"ws://{hp}{WS_PATH}", seed=11)
            await asyncio.wait_for(bot._run(loop=False), timeout=90)

            # Give the finalize txn a moment to commit after game_over.
            row = None
            for _ in range(100):
                async with factory() as session:
                    row = await session.scalar(
                        select(GameRow).where(
                            or_(GameRow.white_bot_id == bot_id, GameRow.black_bot_id == bot_id)
                        )
                    )
                if row is not None and row.result is not None:
                    break
                await asyncio.sleep(0.05)

            assert row is not None, "the SDK's game was not persisted"
            assert row.result in ("white_wins", "black_wins", "draw")

            async with factory() as session:
                persisted_bot = await session.get(BotRow, bot_id)
            assert persisted_bot.games_played >= 1  # rated (V5 finalize path)
    finally:
        await engine.dispose()
