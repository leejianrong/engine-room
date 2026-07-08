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

BOT_WS_PATH = "/api/bot/v1"
DEFAULT_TOKEN = "dev-token"


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
                "time_control": {"base_seconds": base_seconds, "increment_seconds": increment_seconds},
            }
        )
        return self.recv()  # seek_ack (or error)

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
                    {"type": "move", "game_id": msg["game_id"], "ply": msg["ply"], "uci": move.uci()}
                )
            elif kind == "move_ack":
                continue
            elif kind == "game_over":
                return msg
            else:
                raise AssertionError(f"unexpected frame during play: {msg}")
        raise AssertionError("game did not terminate within max_plies")


@contextmanager
def connect(token: str | None = DEFAULT_TOKEN, app=None) -> Iterator[FakeBot]:
    """Open an authenticated bot WebSocket. Pass token=None to omit the header."""
    client = TestClient(app or create_app())
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    with client.websocket_connect(BOT_WS_PATH, headers=headers) as ws:
        yield FakeBot(ws)
