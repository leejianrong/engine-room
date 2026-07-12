"""KAN-61 out-of-process house bots — the flag-ON path end to end (real uvicorn,
real subprocesses, the real `engineroom` SDK, real WS + `crbk_` auth). No DB.

This is the honest test of the mechanism: with `house_bots_out_of_process=True`,
`create_app` wires the `HouseBotClientSupervisor`, whose lifespan `start()` spawns
one subprocess per ambient identity running `sdk/house_bots/runner.py`. Each
subprocess is a plain `engineroom` SDK client (no server imports, ADR-0021) that
dials THIS server's bot WS endpoint, authenticates with a real `crbk_` Bearer key,
and seeks. The two identities share a pool, so the matcher pairs them → a real
house-vs-house game, which we observe in the lobby (`GET /api/games`) and watch run
to completion (it leaves the active list when it finishes).

The server never imports `engineroom`; it only manages subprocesses + provisions
keys. Keys are injected here DB-free via a fake key provider mapping each identity
to a fake `crbk_` key that the `FakeBotAuthenticator` resolves — the same seam the
V7 SDK contract test uses. A short clock + the random engine keep the game fast.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading

import httpx
import uvicorn
from support.fake_client import FakeBotAuthenticator

from engine_room.app import create_app
from engine_room.game.house_bots import JIAN_001_ID, JIAN_001_NAME, JIAN_002_ID, JIAN_002_NAME
from engine_room.game.house_clients import HouseClientSpec
from engine_room.protocol.messages import BotInfo

WS_PATH = "/api/bot/v1"
_GREETER = dict(greeter_solo_wait_seconds=0.0, tick_interval_seconds=0.02)
_HOUSE_NAMES = {JIAN_001_NAME, JIAN_002_NAME}

_KEYS = {JIAN_001_ID: "crbk_house_001", JIAN_002_ID: "crbk_house_002"}


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # off the main thread → no signals
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextlib.asynccontextmanager
async def live_server(port: int, **app_kwargs):
    app = create_app(**app_kwargs)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = _Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        yield f"127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def _poll_games(hostport: str):
    async with httpx.AsyncClient(base_url=f"http://{hostport}") as http:
        resp = await http.get("/api/games")
        return resp.json().get("games", [])


def _house_vs_house(games) -> dict | None:
    for g in games:
        names = {g["white"]["name"], g["black"]["name"]}
        if names <= _HOUSE_NAMES and len(names) == 2:
            return g
    return None


async def test_out_of_process_house_bots_play_a_lobby_game_to_completion():
    authn = FakeBotAuthenticator(
        {
            _KEYS[JIAN_001_ID]: BotInfo(id=JIAN_001_ID, name=JIAN_001_NAME, rating=1200),
            _KEYS[JIAN_002_ID]: BotInfo(id=JIAN_002_ID, name=JIAN_002_NAME, rating=1200),
        }
    )

    async def key_provider(spec: HouseClientSpec) -> str:
        return _KEYS[spec.bot_id]

    # Fast, terminating games: the random engine + a short clock so a full
    # house-vs-house game finishes well within the test timeout.
    specs = [
        HouseClientSpec(JIAN_001_ID, JIAN_001_NAME, "random", 1, (5, 0)),
        HouseClientSpec(JIAN_002_ID, JIAN_002_NAME, "random", 1, (5, 0)),
    ]

    port = _free_port()
    url = f"ws://127.0.0.1:{port}{WS_PATH}"

    async with live_server(
        port,
        bot_authenticator=authn,
        ambient_games=1,
        house_bots_out_of_process=True,
        house_bot_ws_url=url,
        house_bot_specs=specs,
        house_bot_key_provider=key_provider,
        matcher_kwargs=_GREETER,
    ) as hp:
        # 1) The two SDK-client subprocesses connect, auth with crbk_ keys, seek,
        #    and get paired → a house-vs-house game shows up in the lobby.
        entry = None
        for _ in range(600):  # up to ~30s: subprocess spawn + self-connect + pair
            entry = _house_vs_house(await _poll_games(hp))
            if entry is not None:
                break
            await asyncio.sleep(0.05)
        assert entry is not None, "no out-of-process house-vs-house game appeared"
        game_id = entry["game_id"]

        # 2) It runs to completion — the game leaves the active lobby when finished.
        finished = False
        for _ in range(2000):  # generous: a full random game on a 5+0 clock
            games = await _poll_games(hp)
            if not any(g["game_id"] == game_id for g in games):
                finished = True
                break
            await asyncio.sleep(0.05)
        assert finished, "the out-of-process house game never finished"
