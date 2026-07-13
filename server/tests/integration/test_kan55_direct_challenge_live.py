"""KAN-55 direct challenges (end-to-end, real uvicorn + real websockets):

The direct-challenge WS path — a bot seeks with an `opponent_bot_id` to play one
specific bot instead of anonymous Elo matchmaking:

1. two real bots paired **directly to each other** (challenger takes White), both
   get `game_start` immediately — regardless of Elo distance / who is seeking;
2. an **offline** target → non-fatal `error {OPPONENT_UNAVAILABLE}`, no game.

Real websockets (not the sync TestClient) so two sockets can be driven
concurrently on the server's own loop. No DB. Mirrors test_v3_matchmaking_live.
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


async def _hello(ws) -> dict:
    await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
    return json.loads(await ws.recv())  # welcome


async def _challenge(ws, opponent_bot_id, *, base_seconds=180, cid="c1") -> dict:
    await ws.send(
        json.dumps(
            {
                "type": "seek",
                "id": cid,
                "opponent_bot_id": opponent_bot_id,
                "time_control": {"base_seconds": base_seconds, "increment_seconds": 0},
            }
        )
    )
    return json.loads(await ws.recv())  # seek_ack or error


async def _next(ws, timeout=5.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def test_direct_challenge_pairs_the_two_named_bots():
    authn = FakeBotAuthenticator(
        {
            "crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1"),
            "crbk_b": BotInfo(id="bot_b", name="b", rating=1900, owner_id="u2"),
        }
    )
    # Greeter off + a slow tick: prove the pairing is the *direct* one (immediate,
    # far ratings), not an anonymous / greeter match.
    async with live_server(authn, greeter_pools=(), tick_interval_seconds=5.0) as hp:
        async with _connect(hp, "crbk_a") as a, _connect(hp, "crbk_b") as b:
            await _hello(a)
            await _hello(b)  # B is online but not seeking
            ack = await _challenge(a, "bot_b")
            assert ack["type"] == "seek_ack" and ack["status"] == "paired"
            gs_a = await _next(a)
            gs_b = await _next(b)
    assert gs_a["type"] == "game_start" and gs_b["type"] == "game_start"
    assert gs_a["game_id"] == gs_b["game_id"]
    assert gs_a["your_color"] == "white"  # challenger (initiator) takes White
    assert gs_b["your_color"] == "black"
    assert gs_a["opponent"]["id"] == "bot_b"
    assert gs_b["opponent"]["id"] == "bot_a"
    assert "owner_id" not in gs_a["opponent"]  # ownership never leaks (H5)


async def test_direct_challenge_offline_target_is_rejected():
    authn = FakeBotAuthenticator(
        {"crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1")}
    )
    async with live_server(authn, greeter_pools=()) as hp:
        async with _connect(hp, "crbk_a") as a:
            await _hello(a)
            err = await _challenge(a, "bot_ghost")
    assert err["type"] == "error"
    assert err["code"] == "OPPONENT_UNAVAILABLE"
    assert err["fatal"] is False
