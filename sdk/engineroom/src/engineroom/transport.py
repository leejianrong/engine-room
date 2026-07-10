"""WebSocket transport — the thin, swappable seam under the run loop.

A ``Transport`` is anything with async ``send(dict)`` / ``recv() -> dict`` /
``close()`` that raises ``TransportClosed`` when the connection drops. The real
implementation wraps ``websockets``; tests inject an in-memory fake so the run
loop is exercised with no network (mirrors the layered test seams, ADR-0021).
"""

from __future__ import annotations

import json
from typing import Protocol

from .const import ChessroomError


class TransportClosed(ChessroomError):
    """The underlying connection closed (peer gone / network blip). The run loop
    treats this as a reconnect trigger (PROTOCOL §8)."""


class Transport(Protocol):
    async def send(self, message: dict) -> None: ...
    async def recv(self) -> dict: ...
    async def close(self) -> None: ...


class WebSocketTransport:
    """A ``Transport`` backed by the ``websockets`` client (PROTOCOL §1). The API
    key rides the upgrade request's ``Authorization: Bearer`` header (§3) — never
    in the query string, never per-message."""

    def __init__(self, ws) -> None:
        self._ws = ws

    @classmethod
    async def connect(cls, url: str, key: str) -> "WebSocketTransport":
        import websockets

        ws = await websockets.connect(
            url, additional_headers={"Authorization": f"Bearer {key}"}
        )
        return cls(ws)

    async def send(self, message: dict) -> None:
        import websockets

        try:
            await self._ws.send(json.dumps(message))
        except websockets.ConnectionClosed as exc:  # type: ignore[attr-defined]
            raise TransportClosed(str(exc)) from exc

    async def recv(self) -> dict:
        import websockets

        try:
            return json.loads(await self._ws.recv())
        except websockets.ConnectionClosed as exc:  # type: ignore[attr-defined]
            raise TransportClosed(str(exc)) from exc

    async def close(self) -> None:
        try:
            await self._ws.close()
        except Exception:  # pragma: no cover - close is best-effort
            pass
