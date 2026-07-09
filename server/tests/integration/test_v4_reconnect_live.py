"""V4 sub-step 4 checkpoint (end-to-end, real uvicorn + real websockets):

Reconnect-resume — the seam the sync TestClient can't drive (a socket is killed
mid-game and a *new* one is opened while the game loop runs on the server loop):

1. a bot killed mid-game reconnects with the same key, gets welcome.active_game +
   a re-sent your_turn, and finishes the game on the same seat;
2. a blind move-resend after the blip is re-acked, never re-applied (§9).

A lone bot vs the on-demand greeter (house) keeps it to a single real socket.
No DB.
"""

import asyncio
import contextlib
import json
import threading

import chess
import uvicorn
import websockets
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
    return websockets.connect(
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


async def _seek_house_game(ws) -> dict:
    """Seek 3+0; the greeter (fires immediately in these tests) hands back a house
    game. Returns the first your_turn (ply 0, White)."""
    await _send(
        ws,
        {
            "type": "seek",
            "id": "c1",
            "time_control": {"base_seconds": 180, "increment_seconds": 0},
        },
    )
    await _recv(ws)  # seek_ack
    gs = await _recv(ws)  # game_start
    assert gs["type"] == "game_start"
    yt = await _recv(ws)  # your_turn ply 0
    assert yt["type"] == "your_turn" and yt["ply"] == 0
    return gs, yt


def _first_legal(fen: str) -> str:
    return next(iter(chess.Board(fen).legal_moves)).uci()


async def _play_out(ws, max_plies: int = 4000) -> dict:
    for _ in range(max_plies):
        msg = await _recv(ws, timeout=10)
        kind = msg["type"]
        if kind == "your_turn":
            await _send(
                ws,
                {
                    "type": "move",
                    "game_id": msg["game_id"],
                    "ply": msg["ply"],
                    "uci": _first_legal(msg["fen"]),
                },
            )
        elif kind == "move_ack":
            continue
        elif kind == "game_over":
            return msg
        else:
            raise AssertionError(f"unexpected frame during play: {msg}")
    raise AssertionError("game did not terminate")


async def test_reconnect_resumes_same_seat_and_finishes():
    authn = FakeBotAuthenticator(
        {"crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1")}
    )
    async with live_server(
        authn, greeter_solo_wait_seconds=0.0, tick_interval_seconds=0.02
    ) as hp:
        async with _connect(hp, "crbk_a") as a:
            await _hello(a)
            gs, yt = await _seek_house_game(a)
            game_id = gs["game_id"]
        # Socket closed WITHOUT moving — a mid-game blip on the bot's own turn.
        # The clock keeps running; the game is still live and bound.
        async with _connect(hp, "crbk_a") as a2:
            await _send(a2, {"type": "hello", "protocol_version": "1.0"})
            welcome = await _recv(a2)
            assert welcome["type"] == "welcome"
            resume = welcome["active_game"]
            assert resume is not None
            assert resume["game_id"] == game_id
            assert resume["your_color"] == "white"
            assert resume["to_move"] == "white"
            assert resume["ply"] == 0
            # Because it's our move, your_turn is re-sent on the new socket.
            yt2 = await _recv(a2)
            assert yt2["type"] == "your_turn" and yt2["ply"] == 0
            # Answer the resumed turn, then finish the game on the same seat.
            move0 = _first_legal(yt2["fen"])
            await _send(a2, {"type": "move", "game_id": yt2["game_id"], "ply": 0, "uci": move0})
            over = await _play_out(a2)
    assert over["type"] == "game_over"
    assert over["result"] in {"white_wins", "black_wins", "draw"}


async def test_blind_move_resend_is_reacked_not_reapplied():
    authn = FakeBotAuthenticator(
        {"crbk_a": BotInfo(id="bot_a", name="a", rating=1200, owner_id="u1")}
    )
    async with live_server(
        authn, greeter_solo_wait_seconds=0.0, tick_interval_seconds=0.02
    ) as hp:
        async with _connect(hp, "crbk_a") as a:
            await _hello(a)
            _, yt0 = await _seek_house_game(a)
            uci0 = _first_legal(yt0["fen"])
            await _send(a, {"type": "move", "game_id": yt0["game_id"], "ply": 0, "uci": uci0})
            ack0 = await _recv(a)
            assert ack0["type"] == "move_ack" and ack0["ply"] == 0
            yt2 = await _recv(a)  # house replied → our ply-2 turn
            assert yt2["type"] == "your_turn" and yt2["ply"] == 2

            # Blind resend of the ply-0 move (a post-blip retransmit).
            await _send(a, {"type": "move", "game_id": yt2["game_id"], "ply": 0, "uci": uci0})
            reack = await _recv(a)
            assert reack["type"] == "move_ack" and reack["ply"] == 0  # re-acked

            # The board was NOT double-applied: the real ply-2 move still works.
            move2 = _first_legal(yt2["fen"])
            await _send(a, {"type": "move", "game_id": yt2["game_id"], "ply": 2, "uci": move2})
            ack2 = await _recv(a)
            assert ack2["type"] == "move_ack" and ack2["ply"] == 2
