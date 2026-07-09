"""V4 sub-step 5 checkpoint (end-to-end, real uvicorn + real websockets):

Heartbeat + mutual-abandonment ABORT (§10 / ADR-0016 I7):

1. both bots drop mid-game → the game ABORTS (no result, no rating); a
   reconnecting bot is told game_over{termination:"aborted"};
2. a SINGLE drop does NOT abort — the survivor stays live and the dropped bot can
   reconnect and resume (the clock governs, ADR-0025 #3);
3. a bot that never answers `pong` has its half-dead socket closed after the
   (tiny, injected) liveness timeout.

No DB (the abort is observed via the reconnect-delivered game_over, D-vi).
"""

import asyncio
import contextlib
import json
import threading

import pytest
import uvicorn
import websockets
from support.fake_client import FakeBotAuthenticator

from engine_room.app import create_app
from engine_room.protocol.messages import BotInfo

WS_PATH = "/api/bot/v1"


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass


@contextlib.asynccontextmanager
async def live_server(authenticator, *, hb_kwargs=None, **matcher_kwargs):
    app = create_app(
        bot_authenticator=authenticator, matcher_kwargs=matcher_kwargs, hb_kwargs=hb_kwargs
    )
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


async def _connect(hostport: str, key: str):
    return await websockets.connect(
        f"ws://{hostport}{WS_PATH}",
        additional_headers={"Authorization": f"Bearer {key}"},
    )


async def _send(ws, obj: dict) -> None:
    await ws.send(json.dumps(obj))


async def _recv(ws, timeout: float = 5.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def _hello(ws) -> None:
    await _send(ws, {"type": "hello", "protocol_version": "1.0"})
    await _recv(ws)  # welcome


async def _seek(ws, base_seconds: int = 180) -> None:
    await _send(
        ws,
        {
            "type": "seek",
            "id": "c1",
            "time_control": {"base_seconds": base_seconds, "increment_seconds": 0},
        },
    )
    await _recv(ws)  # seek_ack


def _two_bots():
    return FakeBotAuthenticator(
        {
            "crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1"),
            "crbk_b": BotInfo(id="bot_b", name="b", rating=1205, owner_id="u2"),
        }
    )


async def _match_two(hp):
    """Connect + seek two real bots; return their sockets once both are in a game."""
    a = await _connect(hp, "crbk_a")
    b = await _connect(hp, "crbk_b")
    await _hello(a)
    await _hello(b)
    await _seek(a)
    await _seek(b)
    gs_a = await _recv(a)
    gs_b = await _recv(b)
    assert gs_a["type"] == "game_start" and gs_b["type"] == "game_start"
    return a, b, gs_a["game_id"]


async def test_mutual_abandonment_aborts_the_game():
    async with live_server(_two_bots(), greeter_pools=(), tick_interval_seconds=0.02) as hp:
        a, b, game_id = await _match_two(hp)
        # First one drops — a single drop must NOT abort (the other is still live).
        await b.close()
        await asyncio.sleep(0.1)
        # Second one drops — now both seats are gone → ABORT.
        await a.close()
        await asyncio.sleep(0.3)

        # Reconnect A: no active game, but the missed game_over is delivered (D-vi).
        a2 = await _connect(hp, "crbk_a")
        await _send(a2, {"type": "hello", "protocol_version": "1.0"})
        welcome = await _recv(a2)
        assert welcome["active_game"] is None
        over = await _recv(a2)
        await a2.close()

    assert over["type"] == "game_over"
    assert over["result"] == "aborted"
    assert over["termination"] == "aborted"
    assert over["rating"] is None  # ABORTED does not affect rating (§8)


async def test_single_disconnect_does_not_abort():
    async with live_server(_two_bots(), greeter_pools=(), tick_interval_seconds=0.02) as hp:
        a, b, game_id = await _match_two(hp)
        # Only A drops; B stays connected.
        await a.close()
        await asyncio.sleep(0.2)

        # The game is still live: A reconnects and resumes (not aborted).
        a2 = await _connect(hp, "crbk_a")
        await _send(a2, {"type": "hello", "protocol_version": "1.0"})
        welcome = await _recv(a2)
        assert welcome["active_game"] is not None
        assert welcome["active_game"]["game_id"] == game_id
        await a2.close()
        await b.close()


async def test_bot_that_never_pongs_is_disconnected():
    authn = FakeBotAuthenticator(
        {"crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1")}
    )
    async with live_server(
        authn,
        greeter_pools=(),
        hb_kwargs={"ping_interval_seconds": 0.05, "liveness_timeout_seconds": 0.15},
    ) as hp:
        a = await _connect(hp, "crbk_a")
        await _hello(a)
        # Never reply to pings → the server closes the half-dead socket.
        with pytest.raises(websockets.ConnectionClosed):
            for _ in range(200):
                await asyncio.wait_for(a.recv(), timeout=2.0)
