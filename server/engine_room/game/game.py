"""In-memory Game state (ADR-0018 live state is in-memory in the worker).

Lifecycle states per ADR-0010: PAIRED -> IN_PROGRESS -> FINISHED | ABORTED.

V4 (resilience): a running game carries a `LiveState` (board/clock/ply/last-move
+ applied-ply history) that the loop updates each half-move, so a reconnect can
be answered with a consistent `welcome.active_game` snapshot (PROTOCOL §8) no
matter which session is current. Seats are attached at launch (`seats`), and an
`abort` event lets the loop end as ABORTED when both seats are gone (V4 s5).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import chess

from ..protocol.messages import BotInfo, TimeControl
from .clock import Clock

if TYPE_CHECKING:
    from ..ws.session import Session
    from .house_bots import RandomBot

STANDARD_START_FEN = chess.STARTING_FEN


@dataclass
class Participant:
    """One side's identity + how to reach it. Seat is bound to the bot, not the
    session (ADR-0009): a human-owned bot has a live Session; a house bot is
    in-process (session is None, house set)."""

    bot: BotInfo
    session: Optional["Session"] = None
    is_house: bool = False
    house: Optional["RandomBot"] = None


@dataclass
class LiveState:
    """The live, in-memory state of a running game — the source of truth for a
    reconnect snapshot (PROTOCOL §8). The loop mutates this in place each move."""

    board: chess.Board
    clock: Clock
    ply: int = 0  # the next (expected) half-move to be played
    last_move: Optional[dict] = None  # {"uci","san"} of the last applied move
    applied: dict[int, str] = field(default_factory=dict)  # ply -> uci (§9 re-ack)
    # The offerer's color while a draw offer stands ("white"/"black"), or None.
    # Surfaced to the OTHER side via your_turn.opponent_draw_offer; cleared when
    # the recipient makes a move (implicit decline, ADR-0016 D6). V5.
    pending_draw_offer: Optional[str] = None


@dataclass
class Game:
    id: str
    white: Participant
    black: Participant
    time_control: TimeControl
    initial_fen: str
    white_ms: int
    black_ms: int
    created_at: datetime
    state: str = "paired"  # paired | in_progress | finished | aborted
    # Attached at launch (V4): seat by color ("white"/"black") + live state.
    seats: dict = field(default_factory=dict)
    live: Optional[LiveState] = None
    # Set when both seats vanish → run_game ends the game as ABORTED (V4 s5).
    abort: asyncio.Event = field(default_factory=asyncio.Event)
    # Non-move control frames (resign/draw_offer/draw_accept, §7) as (color, msg).
    # The endpoint routes them here — the loop always watches this queue, so a
    # control from the side NOT on move still reaches it (V5 D-a).
    controls: asyncio.Queue = field(default_factory=asyncio.Queue)
    # Terminal record, stashed at game-end so a bot that missed game_over while
    # disconnected can be told the outcome on reconnect (D-vi, delivered in s4).
    result: Optional[str] = None
    termination: Optional[str] = None
    final_fen: Optional[str] = None
    pgn: Optional[str] = None

    def _color_of(self, bot_id: str) -> Optional[str]:
        if self.white.bot.id == bot_id:
            return "white"
        if self.black.bot.id == bot_id:
            return "black"
        return None

    def color_of(self, bot_id: str) -> Optional[str]:
        """This bot's color ("white"/"black") in this game, or None."""
        return self._color_of(bot_id)

    def seat_for(self, bot_id: str):
        """The seat this bot occupies, or None if it isn't in this game."""
        color = self._color_of(bot_id)
        return self.seats.get(color) if color is not None else None

    def resume_payload(self, bot_id: str) -> Optional[dict]:
        """The `welcome.active_game` snapshot for a reconnecting bot (PROTOCOL §8),
        or None if there is no live state / the bot isn't in this game."""
        color = self._color_of(bot_id)
        if color is None or self.live is None:
            return None
        live = self.live
        board = live.board
        return {
            "game_id": self.id,
            "your_color": color,
            "fen": board.fen(),
            "ply": live.ply,
            "last_move": live.last_move,
            "clocks": {
                "white_ms": live.clock.remaining_ms(chess.WHITE),
                "black_ms": live.clock.remaining_ms(chess.BLACK),
            },
            # True if the OTHER side has a draw offer standing against this bot.
            "opponent_draw_offer": (
                live.pending_draw_offer is not None and live.pending_draw_offer != color
            ),
            "to_move": "white" if board.turn == chess.WHITE else "black",
        }
