"""Wire-protocol codec — outbound frame builders + inbound payload views.

Re-derived from docs/design/PROTOCOL.md (v1.0). One JSON object per frame; every
frame has a string ``type``. Durations are integer milliseconds unless the field
name says ``_seconds``; moves are lowercase UCI. This module has NO server imports
(ADR-0021 decoupling).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .const import PROTOCOL_VERSION, SDK_UA

# ---------------------------------------------------------------------------
# Outbound frames (client → server)
# ---------------------------------------------------------------------------


def hello_frame() -> dict:
    return {"type": "hello", "protocol_version": PROTOCOL_VERSION, "sdk": SDK_UA}


def seek_frame(base_seconds: int, increment_seconds: int, cid: str = "seek") -> dict:
    return {
        "type": "seek",
        "id": cid,
        "time_control": {
            "base_seconds": base_seconds,
            "increment_seconds": increment_seconds,
        },
    }


def move_frame(game_id: str, ply: int, uci: str, *, offer_draw: bool = False) -> dict:
    frame = {"type": "move", "game_id": game_id, "ply": ply, "uci": uci}
    if offer_draw:
        frame["offer_draw"] = True
    return frame


def resign_frame(game_id: str) -> dict:
    return {"type": "resign", "game_id": game_id}


def draw_accept_frame(game_id: str) -> dict:
    return {"type": "draw_accept", "game_id": game_id}


def pong_frame(t: int) -> dict:
    return {"type": "pong", "t": t}


# ---------------------------------------------------------------------------
# Inbound payload views (server → client) — thin, read-only projections
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GameStart:
    """A new game has been paired (PROTOCOL §5). Surfaced to ``on_game_start``."""

    game_id: str
    your_color: str
    opponent: dict  # {id, name, rating}
    time_control: dict  # {base_seconds, increment_seconds}
    initial_fen: str
    clocks: dict  # {white_ms, black_ms}
    start_grace_ms: int

    @classmethod
    def from_msg(cls, m: dict) -> "GameStart":
        return cls(
            game_id=m["game_id"],
            your_color=m["your_color"],
            opponent=m.get("opponent", {}),
            time_control=m.get("time_control", {}),
            initial_fen=m.get("initial_fen", ""),
            clocks=m.get("clocks", {}),
            start_grace_ms=m.get("start_grace_ms", 0),
        )

    @classmethod
    def from_active_game(cls, a: dict) -> "GameStart":
        """A partial view synthesized from ``welcome.active_game`` on reconnect
        (PROTOCOL §8) — no opponent/time_control/start_grace in that payload."""
        return cls(
            game_id=a["game_id"],
            your_color=a.get("your_color", ""),
            opponent={},
            time_control={},
            initial_fen=a.get("fen", ""),
            clocks=a.get("clocks", {}),
            start_grace_ms=0,
        )


@dataclass(frozen=True)
class TurnState:
    """It is the bot's turn (PROTOCOL §6). Passed (as a ``chess.Board``) to
    ``choose_move``; the raw state is available for advanced use."""

    game_id: str
    ply: int
    fen: str
    last_move: Optional[dict]  # {uci, san} or None
    clocks: dict  # {white_ms, black_ms}
    your_color: str
    opponent_draw_offer: bool

    @classmethod
    def from_msg(cls, m: dict) -> "TurnState":
        return cls(
            game_id=m["game_id"],
            ply=m["ply"],
            fen=m["fen"],
            last_move=m.get("last_move"),
            clocks=m.get("clocks", {}),
            your_color=m.get("your_color", ""),
            opponent_draw_offer=bool(m.get("opponent_draw_offer", False)),
        )


@dataclass(frozen=True)
class GameOver:
    """A game has ended (PROTOCOL §8). Surfaced to ``on_game_over``."""

    game_id: str
    result: str  # white_wins | black_wins | draw | aborted
    termination: str
    final_fen: str
    pgn: str
    rating: Optional[dict]  # {before, after} — absent for aborted/unrated

    @classmethod
    def from_msg(cls, m: dict) -> "GameOver":
        return cls(
            game_id=m.get("game_id", ""),
            result=m.get("result", ""),
            termination=m.get("termination", ""),
            final_fen=m.get("final_fen", ""),
            pgn=m.get("pgn", ""),
            rating=m.get("rating"),
        )
