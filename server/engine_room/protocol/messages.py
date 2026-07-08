"""Wire messages for the bot WebSocket, mirroring PROTOCOL.md v1.0.

Only the messages needed so far are modeled; more arrive as later sub-steps
implement them (game_start, your_turn, move, move_ack, game_over, ...).

Inbound (client -> server) messages are parsed via `parse_client_message`,
which raises `ProtocolError` (carrying a wire error code) on anything malformed
or unknown. Outbound (server -> client) messages are pydantic models the caller
serializes with `.model_dump_json()`.
"""

from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError


class TimeControl(BaseModel):
    base_seconds: int
    increment_seconds: int = 0


class BotInfo(BaseModel):
    id: str
    name: str
    rating: int


# --- inbound (client -> server) ------------------------------------------------


class Hello(BaseModel):
    type: Literal["hello"]
    protocol_version: str
    sdk: Optional[str] = None


class Seek(BaseModel):
    type: Literal["seek"]
    time_control: TimeControl
    id: Optional[str] = None  # client correlation id, echoed on the ack


class SeekCancel(BaseModel):
    type: Literal["seek_cancel"]
    seek_id: str


class Move(BaseModel):
    type: Literal["move"]
    game_id: str
    ply: int
    uci: str
    id: Optional[str] = None  # client correlation id, echoed on move_ack
    offer_draw: bool = False  # honored in V5


_CLIENT_MODELS: dict[str, type[BaseModel]] = {
    "hello": Hello,
    "seek": Seek,
    "seek_cancel": SeekCancel,
    "move": Move,
}


# --- outbound (server -> client) -----------------------------------------------


class Welcome(BaseModel):
    type: Literal["welcome"] = "welcome"
    protocol_version: str
    session_id: str
    bot: BotInfo
    active_game: Optional[dict] = None


class SeekAck(BaseModel):
    type: Literal["seek_ack"] = "seek_ack"
    seek_id: str
    status: str = "queued"
    id: Optional[str] = None  # echoes the client's seek correlation id


class SeekEnded(BaseModel):
    type: Literal["seek_ended"] = "seek_ended"
    seek_id: str
    reason: str  # "cancelled" | "expired" (TTL, ADR-0016 E8)


class Clocks(BaseModel):
    white_ms: int
    black_ms: int


class GameStart(BaseModel):
    type: Literal["game_start"] = "game_start"
    game_id: str
    your_color: str  # "white" | "black"
    opponent: BotInfo
    time_control: TimeControl
    initial_fen: str
    clocks: Clocks
    start_grace_ms: int = 10000  # PAIRED->IN_PROGRESS grace (ADR-0016 E7)


class YourTurn(BaseModel):
    type: Literal["your_turn"] = "your_turn"
    game_id: str
    ply: int
    fen: str  # full FEN every turn (PROTOCOL.md §6, resolves B5)
    last_move: Optional[dict] = None  # {"uci","san"} of opponent's move, or null
    clocks: Clocks
    your_color: str
    opponent_draw_offer: bool = False


class MoveAck(BaseModel):
    type: Literal["move_ack"] = "move_ack"
    game_id: str
    ply: int
    accepted: bool = True
    id: Optional[str] = None


class Rating(BaseModel):
    before: int
    after: int


class GameOver(BaseModel):
    type: Literal["game_over"] = "game_over"
    game_id: str
    result: str  # white_wins | black_wins | draw | aborted
    termination: str  # ADR-0008 vocabulary
    final_fen: str
    pgn: str
    rating: Optional[Rating] = None  # this bot's Elo change; stubbed in V1, real in V5


class Error(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str = ""
    fatal: bool = False


# --- parsing -------------------------------------------------------------------


class ProtocolError(Exception):
    """A client message that cannot be honored. `code` is a PROTOCOL.md §11 code."""

    def __init__(self, code: str, message: str = "", fatal: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fatal = fatal


def parse_client_message(raw: str) -> BaseModel:
    """Parse one inbound text frame into a typed model, or raise ProtocolError."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise ProtocolError("INVALID_MESSAGE", "malformed JSON")
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        raise ProtocolError("INVALID_MESSAGE", "missing or non-string 'type'")
    model = _CLIENT_MODELS.get(data["type"])
    if model is None:
        raise ProtocolError("INVALID_MESSAGE", f"unknown message type '{data['type']}'")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ProtocolError(
            "INVALID_MESSAGE", f"invalid {data['type']}: {exc.error_count()} error(s)"
        )
