"""Fake bot protocol client — the primary WS test seam (PRD Testing Decisions).

Speaks the raw JSON wire protocol over Starlette's in-process TestClient
WebSocket. This is deliberately NOT the real `chessroom` SDK (separate repo,
ADR-0021): tests assert on the wire contract, and a scripted client can drive
timing-sensitive edge cases deterministically.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

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


@contextmanager
def connect(token: str | None = DEFAULT_TOKEN, app=None) -> Iterator[FakeBot]:
    """Open an authenticated bot WebSocket. Pass token=None to omit the header."""
    client = TestClient(app or create_app())
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    with client.websocket_connect(BOT_WS_PATH, headers=headers) as ws:
        yield FakeBot(ws)
