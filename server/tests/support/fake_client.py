"""Fake bot protocol client — the primary WS test seam (PRD Testing Decisions).

Speaks the raw JSON wire protocol over Starlette's in-process TestClient
WebSocket. This is deliberately NOT the real `chessroom` SDK (separate repo,
ADR-0021): tests assert on the wire contract, and a scripted client can drive
timing-sensitive edge cases deterministically.
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from typing import Any, Iterator

import chess
from starlette.testclient import TestClient

from engine_room.app import create_app
from engine_room.protocol.messages import BotInfo

BOT_WS_PATH = "/api/bot/v1"
# A real-format key (ADR-0014 crbk_ prefix); the fake authenticator maps it to a
# bot identity. V1's stub dev-token is gone (V2 authenticates real keys).
DEFAULT_TOKEN = "crbk_faketoken000000000000000000000000000000"
DEFAULT_BOT = BotInfo(id="bot_dev", name="dev-bot", rating=1200)


class FakeBotAuthenticator:
    """In-memory API-key → BotInfo map — the WS-seam test double (D-c). Unknown
    or empty keys authenticate to None (→ UNAUTHORIZED), like the real one."""

    def __init__(self, mapping: dict[str, BotInfo] | None = None) -> None:
        self._map = dict(mapping or {})

    def add(self, token: str, bot: BotInfo) -> "FakeBotAuthenticator":
        self._map[token] = bot
        return self

    async def authenticate(self, bearer_key: str) -> BotInfo | None:
        return self._map.get(bearer_key)


def default_authenticator() -> FakeBotAuthenticator:
    """A fake authenticator that accepts DEFAULT_TOKEN as DEFAULT_BOT."""
    return FakeBotAuthenticator({DEFAULT_TOKEN: DEFAULT_BOT})


class FakeBot:
    def __init__(self, ws: Any):
        self.ws = ws

    # low-level
    def send(self, message: dict) -> None:
        self.ws.send_json(message)

    def recv(self) -> dict:
        return self.ws.receive_json()

    def expect(self, type_: str) -> dict:
        msg = self.recv()
        assert msg.get("type") == type_, f"expected {type_!r}, got {msg}"
        return msg

    # protocol helpers
    def hello(self, protocol_version: str = "1.0") -> dict:
        self.send({"type": "hello", "protocol_version": protocol_version, "sdk": "fake/0"})
        return self.recv()  # welcome (or error)

    def seek(self, base_seconds: int = 180, increment_seconds: int = 0, cid: str = "c1") -> dict:
        self.send(
            {
                "type": "seek",
                "id": cid,
                "time_control": {
                    "base_seconds": base_seconds,
                    "increment_seconds": increment_seconds,
                },
            }
        )
        return self.recv()  # seek_ack (or error)

    def seek_cancel(self, seek_id: str) -> dict:
        self.send({"type": "seek_cancel", "seek_id": seek_id})
        return self.recv()  # seek_ended (or error)

    def pong(self, t: int = 0) -> None:
        self.send({"type": "pong", "t": t})

    def play_out(self, seed: int = 0, max_plies: int = 4000) -> dict:
        """Play random legal moves in response to each your_turn until game_over.

        Returns the game_over message. Raises on any error frame or if the game
        runs impossibly long (guards against a hang).
        """
        rng = random.Random(seed)
        for _ in range(max_plies):
            msg = self.recv()
            kind = msg["type"]
            if kind == "your_turn":
                board = chess.Board(msg["fen"])
                move = rng.choice(list(board.legal_moves))
                self.send(
                    {
                        "type": "move",
                        "game_id": msg["game_id"],
                        "ply": msg["ply"],
                        "uci": move.uci(),
                    }
                )
            elif kind == "move_ack":
                continue
            elif kind == "ping":
                self.pong(msg.get("t", 0))  # keep the heartbeat happy (§10)
            elif kind == "game_over":
                return msg
            else:
                raise AssertionError(f"unexpected frame during play: {msg}")
        raise AssertionError("game did not terminate within max_plies")


@contextmanager
def connect(
    token: str | None = DEFAULT_TOKEN, app=None, authenticator=None, always_pair: bool = False
) -> Iterator[FakeBot]:
    """Open an authenticated bot WebSocket. Pass token=None to omit the header.

    Builds an app with a FakeBotAuthenticator (accepting DEFAULT_TOKEN) unless an
    `app` or `authenticator` is supplied — so existing single-bot tests keep
    working while newest-wins/multi-bot tests can inject their own identities.

    `always_pair=True` wires V1's synchronous always-pair-vs-house queue so a lone
    seek yields an instant `game_start` (deterministic, no matcher loop) — for the
    game-loop/pairing tests that exercise the game, not V3 matchmaking. Left False,
    the real Elo matcher is used (its WS pairing behavior is covered by the
    live-uvicorn integration tests, D-iv)."""
    if app is None:
        app = create_app(
            bot_authenticator=authenticator or default_authenticator(),
            always_pair=always_pair,
        )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    with client.websocket_connect(BOT_WS_PATH, headers=headers) as ws:
        yield FakeBot(ws)
