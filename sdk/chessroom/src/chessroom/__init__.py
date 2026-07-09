"""chessroom — the official Python SDK for Engine Room.

Write a bot in a few lines:

    from chessroom import Bot
    import random

    class MyBot(Bot):
        def choose_move(self, board):
            return random.choice(list(board.legal_moves))

    MyBot().run(loop=True)   # reads CHESSROOM_KEY / CHESSROOM_URL from the env

The SDK owns the WebSocket transport, the authenticated handshake, reconnect,
heartbeats, and all protocol (de)serialization (ADR-0021); you implement only
``choose_move(board) -> move`` over a ``python-chess`` board.
"""

from __future__ import annotations

from .bot import Bot
from .bots import MinimaxBot, RandomBot
from .const import (
    ACCEPT_DRAW,
    DEFAULT_URL,
    PROTOCOL_VERSION,
    RESIGN,
    SDK_VERSION,
    ChessroomError,
    ConfigError,
    ProtocolError,
)
from .protocol import GameOver, GameStart, TurnState
from .transport import Transport, TransportClosed, WebSocketTransport

# UCIBot is imported lazily by name to keep `import chessroom` cheap and avoid
# importing chess.engine unless the bridge is actually used.
from .uci import UCIBot  # noqa: E402

__version__ = SDK_VERSION

__all__ = [
    "Bot",
    "RandomBot",
    "MinimaxBot",
    "UCIBot",
    "RESIGN",
    "ACCEPT_DRAW",
    "DEFAULT_URL",
    "PROTOCOL_VERSION",
    "GameStart",
    "GameOver",
    "TurnState",
    "Transport",
    "TransportClosed",
    "WebSocketTransport",
    "ChessroomError",
    "ConfigError",
    "ProtocolError",
    "__version__",
]
