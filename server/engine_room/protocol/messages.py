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


_CLIENT_MODELS: dict[str, type[BaseModel]] = {
    "hello": Hello,
    "seek": Seek,
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
        raise ProtocolError("INVALID_MESSAGE", f"invalid {data['type']}: {exc.error_count()} error(s)")
