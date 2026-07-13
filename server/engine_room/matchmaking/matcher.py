"""EloMatchmaker (N3, thickened) — real Elo pools behind `MatchmakingQueue` (R6).

Replaces `AlwaysPairQueue`. A `seek` enrolls a `Ticket` in its time-control pool
and returns immediately (`seek_ack`); a **background loop** pairs tickets and
delivers `game_start` **asynchronously** via the injected `GameLauncher` (a change
from V1/V2's synchronous always-pair, ADR-0025). One `tick()` per pool:

1. reap tickets whose live Session vanished (E7 no-show: a bot that dropped
   between seek and pairing is never paired; the survivor stays enrolled — D-g);
2. expire tickets past the TTL → `seek_ended{expired}` (E8);
3. pair the closest-rated eligible real bots (widening window, same-owner
   exclusion, soft anti-rematch — see `elo`/`pool`);
4. in a *greeter* pool, give a lonely ticket a house game after a short solo wait
   (Kind-2 house, D-i / ADR-0022).

Single-process, in-memory (R5, ADR-0025 #2); a Redis-backed impl swaps in behind
the same interface. An injectable `now` (default `time.monotonic`) makes widening
and TTL deterministic in tests (D-d).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Callable, Iterable, Optional

from ..game.game import Participant
from ..ids import new_id
from ..protocol.messages import SeekEnded, TimeControl
from .elo import Windowing
from .pool import best_opponent
from .queue import PairResult, SeekError
from .ticket import Ticket, tc_key

if TYPE_CHECKING:
    from ..game.house_bots import RandomBot
    from ..game.registry import GameRegistry
    from ..ws.session import Session
    from ..ws.session_registry import SessionRegistry
    from .launcher import GameLauncher

logger = logging.getLogger(__name__)


class EloMatchmaker:
    def __init__(
        self,
        registry: "GameRegistry",
        session_registry: "SessionRegistry",
        launcher: "GameLauncher",
        house_bot: "RandomBot",
        *,
        windowing: Windowing | None = None,
        ticket_ttl_seconds: float = 120.0,
        tick_interval_seconds: float = 0.5,
        greeter_solo_wait_seconds: float = 3.0,
        greeter_pools: Iterable[str] = ("180+0",),
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._session_registry = session_registry
        self._launcher = launcher
        self._house = house_bot
        self._windowing = windowing or Windowing()
        self._ttl = ticket_ttl_seconds
        self._tick_interval = tick_interval_seconds
        self._greeter_wait = greeter_solo_wait_seconds
        self._greeter_pools = frozenset(greeter_pools)
        self._now = now

        self._pools: dict[str, list[Ticket]] = {}
        self._by_seek: dict[str, Ticket] = {}
        self._last_opponent: dict[str, str] = {}  # anti-rematch (E5), by bot id
        self._event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._closing = False

    # --- MatchmakingQueue interface ------------------------------------------

    async def seek(
        self,
        session: "Session",
        time_control: TimeControl,
        opponent_bot_id: Optional[str] = None,
    ) -> PairResult:
        if opponent_bot_id is not None:
            # KAN-55: a direct challenge is paired *synchronously* against the
            # named bot (or rejected) — it never enrolls a queue ticket / TTL.
            return await self._direct_challenge(session, time_control, opponent_bot_id)
        key = tc_key(time_control)
        seek_id = new_id("seek")
        ticket = Ticket(
            seek_id=seek_id,
            session=session,
            time_control=time_control,
            tc_key=key,
            enqueued_at=self._now(),
        )
        self._pools.setdefault(key, []).append(ticket)
        self._by_seek[seek_id] = ticket
        self._event.set()  # nudge the loop to try pairing now
        return PairResult(seek_id=seek_id, game=None)

    async def cancel(self, seek_id: str) -> None:
        ticket = self._by_seek.pop(seek_id, None)
        if ticket is None:
            return
        self._drop(ticket)
        with contextlib.suppress(Exception):
            await ticket.session.send(SeekEnded(seek_id=seek_id, reason="cancelled"))

    async def start(self) -> None:
        if self._task is None:
            self._closing = False
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._closing = True
        if self._task is not None:
            self._event.set()
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    # --- loop ----------------------------------------------------------------

    async def _run(self) -> None:
        while not self._closing:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._event.wait(), timeout=self._tick_interval)
            self._event.clear()
            try:
                await self.tick()
            except Exception:  # never let the matcher loop die on one bad tick
                logger.exception("matcher tick failed")

    async def tick(self) -> None:
        """One pairing pass over every pool. Directly callable in tests."""
        now = self._now()
        for key, pool in self._pools.items():
            await self._tick_pool(key, pool, now)

    async def _tick_pool(self, key: str, pool: list[Ticket], now: float) -> None:
        self._reap_dead(pool)
        await self._expire(pool, now)
        await self._pair_reals(key, pool, now)
        if key in self._greeter_pools:
            await self._greet(pool, now)

    # --- tick stages ---------------------------------------------------------

    def _reap_dead(self, pool: list[Ticket]) -> None:
        """Drop tickets whose Session is no longer the live one (disconnected or
        replaced between seek and pairing) — the E7 no-show case (D-g)."""
        alive = []
        for t in pool:
            if self._session_registry.current(t.bot_id) is t.session:
                alive.append(t)
            else:
                self._by_seek.pop(t.seek_id, None)
        pool[:] = alive

    async def _expire(self, pool: list[Ticket], now: float) -> None:
        live = []
        for t in pool:
            if now - t.enqueued_at >= self._ttl:
                self._by_seek.pop(t.seek_id, None)
                with contextlib.suppress(Exception):
                    await t.session.send(SeekEnded(seek_id=t.seek_id, reason="expired"))
            else:
                live.append(t)
        pool[:] = live

    async def _pair_reals(self, key: str, pool: list[Ticket], now: float) -> None:
        paired = True
        while paired:
            paired = False
            pool.sort(key=lambda t: t.enqueued_at)  # oldest first
            for t in pool:
                excluded = frozenset(
                    {self._last_opponent[t.bot_id]}
                    if t.bot_id in self._last_opponent
                    else ()
                )
                opp = best_opponent(
                    t,
                    [c for c in pool if c is not t],
                    now,
                    self._windowing,
                    excluded=excluded,
                )
                if opp is not None:
                    await self._start_pair(t, opp)
                    self._drop(t)
                    self._drop(opp)
                    paired = True
                    break

    async def _greet(self, pool: list[Ticket], now: float) -> None:
        for t in list(pool):
            if now - t.enqueued_at >= self._greeter_wait:
                await self._start_greeter(t)
                self._drop(t)

    # --- direct challenge (KAN-55) -------------------------------------------

    async def _direct_challenge(
        self, session: "Session", time_control: TimeControl, opponent_bot_id: str
    ) -> PairResult:
        """Pair the seeker directly against a named bot, bypassing Elo/window
        matchmaking. Immediate: either a game (challenger = White, the initiator)
        or a rejection. Edge cases mirror the anonymous rules (same-owner
        exclusion H5; house bots — owner None — are exempt)."""
        seek_id = new_id("seek")
        challenger = session.bot

        def rejected(code: str, message: str) -> PairResult:
            return PairResult(seek_id=seek_id, error=SeekError(code=code, message=message))

        if opponent_bot_id == challenger.id:
            return rejected("INVALID_CHALLENGE", "cannot challenge yourself")
        if self._registry.active_game_for(challenger.id) is not None:
            return rejected("INVALID_CHALLENGE", "you are already in a game")

        target_session = self._session_registry.current(opponent_bot_id)
        if target_session is None:
            return rejected("OPPONENT_UNAVAILABLE", "opponent is not online")
        target = target_session.bot
        # Same-owner exclusion (H5): never pit two bots owned by the same user
        # against each other — rated self-play would farm Elo. House bots
        # (owner_id None) are exempt, so a house bot is always challengeable.
        if challenger.owner_id is not None and challenger.owner_id == target.owner_id:
            return rejected("INVALID_CHALLENGE", "cannot challenge your own bot")
        if self._registry.active_game_for(opponent_bot_id) is not None:
            return rejected("OPPONENT_UNAVAILABLE", "opponent is already in a game")

        # Drop any waiting queue tickets for either bot so the background matcher
        # can't also pair them elsewhere; the target gets game_start (a paired
        # ticket never receives seek_ended).
        self._drop_by_bot(challenger.id)
        self._drop_by_bot(opponent_bot_id)

        game = self._registry.create_game(
            white=Participant(bot=challenger, session=session),
            black=Participant(bot=target, session=target_session),
            time_control=time_control,
        )
        self._last_opponent[challenger.id] = opponent_bot_id  # soft anti-rematch (E5)
        self._last_opponent[opponent_bot_id] = challenger.id
        return PairResult(seek_id=seek_id, game=game, status="paired")

    def _drop_by_bot(self, bot_id: str) -> None:
        """Remove every waiting ticket belonging to `bot_id` from all pools."""
        for pool in self._pools.values():
            for t in list(pool):
                if t.bot_id == bot_id:
                    self._drop(t)

    # --- game creation -------------------------------------------------------

    async def _start_pair(self, a: Ticket, b: Ticket) -> None:
        # Oldest ticket takes White (deterministic — no RNG/wall-clock).
        white_t, black_t = (a, b) if a.enqueued_at <= b.enqueued_at else (b, a)
        game = self._registry.create_game(
            white=Participant(bot=white_t.session.bot, session=white_t.session),
            black=Participant(bot=black_t.session.bot, session=black_t.session),
            time_control=white_t.time_control,
        )
        self._last_opponent[a.bot_id] = b.bot_id  # soft anti-rematch (E5)
        self._last_opponent[b.bot_id] = a.bot_id
        await self._launcher.launch(game)

    async def _start_greeter(self, t: Ticket) -> None:
        # Seeking bot takes White; the house greeter takes Black (no anti-rematch
        # record — the greeter must stay available as a fallback).
        game = self._registry.create_game(
            white=Participant(bot=t.session.bot, session=t.session),
            black=Participant(bot=self._house.info, is_house=True, house=self._house),
            time_control=t.time_control,
        )
        await self._launcher.launch(game)

    def _drop(self, ticket: Ticket) -> None:
        self._by_seek.pop(ticket.seek_id, None)
        pool = self._pools.get(ticket.tc_key)
        if pool is not None and ticket in pool:
            pool.remove(ticket)
