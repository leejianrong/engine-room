"""V3 sub-step 5 checkpoint (end-to-end, real uvicorn + real websockets):

The Elo matcher's WS behavior — the seam the sync TestClient can't drive
deterministically (async game_start + a background loop, D-iv):

1. two real bots matched **to each other** by Elo (not to the house);
2. **same-owner** bots are never paired → both seeks expire;
3. a **lonely** seek expires → seek_ended{expired};
4. **seek_cancel** → seek_ended{cancelled};
5. the **greeter** gives a lone 3+0 seeker a house game (Kind-2, ADR-0022).

Real websockets (not the sync TestClient) so two sockets can be awaited
concurrently while the matcher loop runs on the server's own loop. No DB.
"""

import asyncio
import contextlib
import json
import threading

import uvicorn
from support.fake_client import FakeBotAuthenticator

from engine_room.app import create_app
from engine_room.protocol.messages import BotInfo

WS_PATH = "/api/bot/v1"


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # off the main thread → no signals
        pass


@contextlib.asynccontextmanager
async def live_server(authenticator, **matcher_kwargs):
    app = create_app(bot_authenticator=authenticator, matcher_kwargs=matcher_kwargs)
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
    import websockets

    return websockets.connect(
        f"ws://{hostport}{WS_PATH}",
        additional_headers={"Authorization": f"Bearer {key}"},
    )


async def _hello_seek(ws, *, base_seconds=180):
    await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
    await ws.recv()  # welcome
    await ws.send(
        json.dumps(
            {
                "type": "seek",
                "id": "c1",
                "time_control": {"base_seconds": base_seconds, "increment_seconds": 0},
            }
        )
    )
    return json.loads(await ws.recv())  # seek_ack


async def _next(ws, timeout=5.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def test_two_real_bots_matched_to_each_other_by_elo():
    authn = FakeBotAuthenticator(
        {
            "crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1"),
            "crbk_b": BotInfo(id="bot_b", name="b", rating=1210, owner_id="u2"),
        }
    )
    # Greeter off so they must pair with each other, not with the house.
    async with live_server(authn, greeter_pools=(), tick_interval_seconds=0.05) as hp:
        async with _connect(hp, "crbk_a") as a, _connect(hp, "crbk_b") as b:
            ack_a = await _hello_seek(a)
            ack_b = await _hello_seek(b)
            assert ack_a["type"] == "seek_ack" and ack_b["type"] == "seek_ack"
            gs_a = await _next(a)
            gs_b = await _next(b)
    assert gs_a["type"] == "game_start" and gs_b["type"] == "game_start"
    assert gs_a["opponent"]["id"] == "bot_b"
    assert gs_b["opponent"]["id"] == "bot_a"
    assert gs_a["game_id"] == gs_b["game_id"]
    assert "owner_id" not in gs_a["opponent"]  # ownership never leaks (H5)


async def test_same_owner_bots_are_never_paired():
    authn = FakeBotAuthenticator(
        {
            "crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="same"),
            "crbk_b": BotInfo(id="bot_b", name="b", rating=1200, owner_id="same"),
        }
    )
    async with live_server(
        authn, greeter_pools=(), ticket_ttl_seconds=1.0, tick_interval_seconds=0.05
    ) as hp:
        async with _connect(hp, "crbk_a") as a, _connect(hp, "crbk_b") as b:
            await _hello_seek(a)
            await _hello_seek(b)
            # No pairing; both tickets run to the TTL and expire.
            ea = await _next(a, timeout=5)
            eb = await _next(b, timeout=5)
    assert ea["type"] == "seek_ended" and ea["reason"] == "expired"
    assert eb["type"] == "seek_ended" and eb["reason"] == "expired"


async def test_lonely_seek_expires():
    authn = FakeBotAuthenticator(
        {"crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1")}
    )
    async with live_server(
        authn, greeter_pools=(), ticket_ttl_seconds=1.0, tick_interval_seconds=0.05
    ) as hp:
        async with _connect(hp, "crbk_a") as a:
            ack = await _hello_seek(a, base_seconds=300)  # 5+0, no greeter
            assert ack["type"] == "seek_ack"
            ended = await _next(a, timeout=5)
    assert ended["type"] == "seek_ended"
    assert ended["reason"] == "expired"
    assert ended["seek_id"] == ack["seek_id"]


async def test_seek_cancel_ends_the_seek():
    authn = FakeBotAuthenticator(
        {"crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1")}
    )
    async with live_server(authn, greeter_pools=()) as hp:
        async with _connect(hp, "crbk_a") as a:
            ack = await _hello_seek(a, base_seconds=300)
            await a.send(json.dumps({"type": "seek_cancel", "seek_id": ack["seek_id"]}))
            ended = await _next(a)
    assert ended["type"] == "seek_ended"
    assert ended["reason"] == "cancelled"
    assert ended["seek_id"] == ack["seek_id"]


async def test_greeter_gives_a_lone_3plus0_seeker_a_house_game():
    authn = FakeBotAuthenticator(
        {"crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1")}
    )
    # 3+0 greeter enabled, fires immediately.
    async with live_server(
        authn, greeter_solo_wait_seconds=0.0, tick_interval_seconds=0.02
    ) as hp:
        async with _connect(hp, "crbk_a") as a:
            await _hello_seek(a, base_seconds=180)
            gs = await _next(a)
    assert gs["type"] == "game_start"
    assert gs["opponent"]["name"] == "house-random"
