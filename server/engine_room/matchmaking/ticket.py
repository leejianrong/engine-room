"""A MatchmakingTicket — a Bot's live request to play (ADR-0009/0010 QUEUED).

A ticket waits in a per-time-control pool until the matcher pairs it (→ a Game)
or it expires (→ seek_ended). Identity/rating/owner are read from the ticket's
live `Session` (the bot that seeked), so a rotated/replaced session is reflected
without copying state. Single-process, in-memory (R5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..protocol.messages import TimeControl

if TYPE_CHECKING:
    from ..ws.session import Session


def tc_key(time_control: TimeControl) -> str:
    """Pool key for a time control, e.g. 3+0 → "180+0", 5+0 → "300+0"."""
    return f"{time_control.base_seconds}+{time_control.increment_seconds}"


@dataclass
class Ticket:
    seek_id: str
    session: "Session"
    time_control: TimeControl
    tc_key: str
    enqueued_at: float  # matcher-clock timestamp (D-d)

    @property
    def bot_id(self) -> str:
        return self.session.bot.id

    @property
    def owner_id(self) -> str | None:
        return self.session.bot.owner_id

    @property
    def rating(self) -> int:
        return self.session.bot.rating
