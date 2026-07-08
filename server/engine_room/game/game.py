"""In-memory Game state (ADR-0018 live state is in-memory in the worker).

Lifecycle states per ADR-0010: PAIRED -> IN_PROGRESS -> FINISHED | ABORTED.
Sub-step 3 creates games in PAIRED and advertises game_start; the board, ply,
clocks-running, and terminal handling arrive with the game loop (sub-step 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import chess

from ..protocol.messages import BotInfo, TimeControl

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
class Game:
    id: str
    white: Participant
    black: Participant
    time_control: TimeControl
    initial_fen: str
    white_ms: int
    black_ms: int
    state: str = "paired"  # paired | in_progress | finished | aborted
