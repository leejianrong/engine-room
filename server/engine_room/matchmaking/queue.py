"""Matchmaking behind an interface (R6, ADR-0025).

V1 sub-step 3 = AlwaysPairQueue: every seek is immediately paired against a
house bot, so a newcomer always gets a game (ADR-0022). Real Elo pools / TTL /
same-owner exclusion (V3) and a Redis-backed impl (scale-out) swap in behind
this same `MatchmakingQueue` interface — the WS endpoint never changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol

from ..game.game import Participant
from ..ids import new_id
from ..protocol.messages import TimeControl

if TYPE_CHECKING:
    from ..game.game import Game
    from ..game.house_bots import RandomBot
    from ..game.registry import GameRegistry
    from ..ws.session import Session


@dataclass
class PairResult:
    """Outcome of a seek: always a seek_id; a game if pairing happened now."""

    seek_id: str
    game: Optional["Game"] = None


class MatchmakingQueue(Protocol):
    async def seek(self, session: "Session", time_control: TimeControl) -> PairResult:
        ...

    async def cancel(self, seek_id: str) -> None:
        ...


class AlwaysPairQueue:
    def __init__(self, registry: "GameRegistry", house: "RandomBot") -> None:
        self._registry = registry
        self._house = house

    async def seek(self, session: "Session", time_control: TimeControl) -> PairResult:
        # V1: the seeking bot takes White; the house bot takes Black.
        game = self._registry.create_game(
            white=Participant(bot=session.bot, session=session),
            black=Participant(bot=self._house.info, is_house=True, house=self._house),
            time_control=time_control,
        )
        return PairResult(seek_id=new_id("seek"), game=game)

    async def cancel(self, seek_id: str) -> None:
        # No queue wait in always-pair mode; nothing to cancel. Real TTL/cancel in V3.
        return None
