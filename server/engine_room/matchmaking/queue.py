"""Matchmaking queue behind an interface (R6, ADR-0025).

V1 sub-step 2 only *records* seeks and hands back a seek_id for the ack. The
always-pair-vs-house-bot behavior (sub-step 3) and real Elo pools / TTL /
same-owner exclusion (V3) swap in behind this same interface — the WS endpoint
never changes. A Redis-backed impl slots in here at multi-worker scale-out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..ids import new_id
from ..protocol.messages import TimeControl

if TYPE_CHECKING:
    from ..ws.session import Session


@dataclass
class Ticket:
    seek_id: str
    session: "Session"
    time_control: TimeControl


class MatchmakingQueue(Protocol):
    async def add_seek(self, session: "Session", time_control: TimeControl) -> str:
        """Enqueue a seek; return its seek_id."""
        ...

    async def cancel(self, seek_id: str) -> None:
        ...


class InMemoryQueue:
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}

    async def add_seek(self, session: "Session", time_control: TimeControl) -> str:
        seek_id = new_id("seek")
        self._tickets[seek_id] = Ticket(seek_id, session, time_control)
        return seek_id

    async def cancel(self, seek_id: str) -> None:
        self._tickets.pop(seek_id, None)
