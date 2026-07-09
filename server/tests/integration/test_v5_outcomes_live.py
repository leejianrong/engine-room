"""V5 (end-to-end, real uvicorn + real websockets): resign and draw-by-agreement
between two real bots — the seam the sync TestClient can't drive (async pairing +
two sockets awaited concurrently). No DB → game_over carries a stubbed rating;
the real-DB Elo write is asserted in test_v5_ratings_finalize.py."""

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
    def install_signal_handlers(self) -> None:
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
        yield f"127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _connect(hostport: str, key: str):
    import websockets

    return websockets.connect(
        f"ws://{hostport}{WS_PATH}",
        additional_headers={"Authorization": f"Bearer {key}"},
    )


async def _next(ws, timeout=5.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def _hello_seek(ws):
    await ws.send(json.dumps({"type": "hello", "protocol_version": "1.0"}))
    await ws.recv()  # welcome
    await ws.send(
        json.dumps({"type": "seek", "id": "c1",
                    "time_control": {"base_seconds": 180, "increment_seconds": 0}})
    )
    return json.loads(await ws.recv())  # seek_ack


def _two_bots():
    return FakeBotAuthenticator(
        {
            "crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1"),
            "crbk_b": BotInfo(id="bot_b", name="b", rating=1200, owner_id="u2"),
        }
    )


async def _pair(a, b):
    """Seek both, return (white_ws, black_ws) by the game_start colors."""
    await _hello_seek(a)
    await _hello_seek(b)
    gs_a = await _next(a)
    gs_b = await _next(b)
    assert gs_a["type"] == "game_start" and gs_b["type"] == "game_start"
    return (a, b) if gs_a["your_color"] == "white" else (b, a)


async def test_resign_between_two_bots():
    async with live_server(_two_bots(), greeter_pools=(), tick_interval_seconds=0.05) as hp:
        async with _connect(hp, "crbk_a") as a, _connect(hp, "crbk_b") as b:
            white, black = await _pair(a, b)
            yt = await _next(white)  # White on move
            assert yt["type"] == "your_turn"
            await white.send(json.dumps({"type": "resign", "game_id": yt["game_id"]}))
            over_w = await _next(white)
            over_b = await _next(black)

    assert over_w["termination"] == "resignation"
    assert over_w["result"] == "black_wins"  # White resigned
    assert over_b["result"] == "black_wins"


async def test_draw_by_agreement_between_two_bots():
    async with live_server(_two_bots(), greeter_pools=(), tick_interval_seconds=0.05) as hp:
        async with _connect(hp, "crbk_a") as a, _connect(hp, "crbk_b") as b:
            white, black = await _pair(a, b)
            yt_w = await _next(white)  # ply 0
            # White plays e2e4 with a piggybacked draw offer (D6).
            await white.send(json.dumps({
                "type": "move", "game_id": yt_w["game_id"], "ply": 0,
                "uci": "e2e4", "offer_draw": True,
            }))
            await _next(white)  # move_ack
            yt_b = await _next(black)  # ply 1 — offer surfaced
            assert yt_b["type"] == "your_turn"
            assert yt_b["opponent_draw_offer"] is True
            await black.send(json.dumps({"type": "draw_accept", "game_id": yt_b["game_id"]}))
            over_w = await _next(white)
            over_b = await _next(black)

    assert over_w["result"] == "draw" and over_w["termination"] == "agreement"
    assert over_b["result"] == "draw" and over_b["termination"] == "agreement"
