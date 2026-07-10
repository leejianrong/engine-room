"""Constants, sentinels, and errors for the engineroom SDK.

These re-derive from the public wire protocol (docs/design/PROTOCOL.md); the SDK
never imports server code (ADR-0021).
"""

from __future__ import annotations

__all__ = [
    "PROTOCOL_VERSION",
    "SDK_VERSION",
    "SDK_UA",
    "DEFAULT_URL",
    "RESIGN",
    "ACCEPT_DRAW",
    "ChessroomError",
    "ConfigError",
    "ProtocolError",
]

# The semver protocol version this SDK speaks (PROTOCOL §2). The server advertises
# a supported range and replies VERSION_UNSUPPORTED if we're out of range.
PROTOCOL_VERSION = "1.0"
SDK_VERSION = "0.1.0"
SDK_UA = f"engineroom-py/{SDK_VERSION}"

# Default WebSocket endpoint — the live platform (PROTOCOL §1, major version in the
# path). Override with CHESSROOM_URL or Bot(url=...) for local dev
# (ws://localhost:8001/api/bot/v1).
DEFAULT_URL = "wss://engine-room.fly.dev/api/bot/v1"


class _Sentinel:
    """A unique, printable marker returned from choose_move() to signal an
    action other than a move (PROTOCOL §7)."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"engineroom.{self._name}"


#: Return from ``choose_move`` to resign the game (opponent wins). PROTOCOL §7.
RESIGN = _Sentinel("RESIGN")
#: Return from ``choose_move`` when ``state.opponent_draw_offer`` is set to accept
#: the draw (→ ``agreement``). PROTOCOL §7. Returning a normal move declines it.
ACCEPT_DRAW = _Sentinel("ACCEPT_DRAW")


class ChessroomError(Exception):
    """Base class for all SDK errors."""


class ConfigError(ChessroomError):
    """Missing/invalid configuration (e.g. no API key)."""


class ProtocolError(ChessroomError):
    """The server sent an unexpected or fatal frame (see PROTOCOL §11)."""
