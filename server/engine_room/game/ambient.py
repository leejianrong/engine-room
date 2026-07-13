"""Ambient house bots (ADR-0022 Kind-1, V6 D-g) — keep the spectator lobby alive
with zero real users.

A background supervisor maintains a fixed number of **house-vs-house** games:
whenever one finishes it spawns a replacement, so the lobby always shows live
play. The games are created directly (NOT via the matcher pool), so they never
interfere with real-vs-real pairing, same-owner exclusion, anti-rematch, or the
greeter (Kind 2). They are launched through the normal `GameLauncher`, so they
persist to Postgres and rate both house bots via the V5 finalizer (rated +
persisted — V6 Q4); a finished ambient game is evicted from the in-memory
registry (its record + replay live in Postgres) so `_games` stays bounded under
the endless stream.

Single-process/in-memory (R5). Started/stopped by the app lifespan; disabled
when `n == 0` (the CI/unit default).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Sequence

from ..protocol.messages import BotInfo, TimeControl
from .game import Participant

if TYPE_CHECKING:
    from ..matchmaking.launcher import GameLauncher
    from .house_bots import RandomBot
    from .registry import GameRegistry

# Reads a bot's current persisted rating by id (None if the row is missing). See
# `house_clients.make_db_rating_provider`.
RatingProvider = Callable[[str], Awaitable[Optional[int]]]


def parse_pool(pool: str) -> TimeControl:
    """`"<base>+<increment>"` seconds → TimeControl (e.g. "180+0" → 3+0)."""
    base, _, inc = pool.partition("+")
    return TimeControl(base_seconds=int(base), increment_seconds=int(inc or 0))


class AmbientSupervisor:
    def __init__(
        self,
        registry: "GameRegistry",
        launcher: "GameLauncher",
        house_a: "RandomBot",
        house_b: "RandomBot",
        *,
        n: int,
        time_controls: Sequence[TimeControl],
        rating_provider: "Optional[RatingProvider]" = None,
    ) -> None:
        self._registry = registry
        self._launcher = launcher
        self._house_a = house_a
        self._house_b = house_b
        self._n = n
        # Optional per-launch rating refresh (KAN-207). None → use the house bot
        # object's static rating (the fast/test default, no DB).
        self._rating_provider = rating_provider
        # KAN-57: round-robin a rotation of time controls across the `n` slots, so
        # the lobby shows a mix (e.g. 3+0, bullet 1+0, 2+1 increment) rather than a
        # single control. `_spawn_count` advances on every spawn AND refill, so the
        # rotation keeps cycling as finished games are replaced.
        self._tcs: list[TimeControl] = list(time_controls)
        if not self._tcs:
            raise ValueError("AmbientSupervisor needs at least one time control")
        self._spawn_count = 0
        self._live: dict[asyncio.Task, str] = {}  # task -> game_id
        self._refills: set[asyncio.Task] = set()
        self._closing = False
        self._started = False

    async def start(self) -> None:
        if self._started or self._n <= 0:
            return
        self._started = True
        self._closing = False
        await self._refill()

    async def stop(self) -> None:
        self._closing = True
        for task in list(self._live) + list(self._refills):
            task.cancel()
        for task in list(self._live) + list(self._refills):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        # Evict the cancelled games now (the done-callbacks fire on a later loop
        # turn, so don't rely on them for deterministic shutdown).
        for game_id in self._live.values():
            self._registry.remove(game_id)
        self._live.clear()
        self._refills.clear()
        self._started = False

    async def _refill(self) -> None:
        while not self._closing and len(self._live) < self._n:
            await self._spawn_one()

    async def _spawn_one(self) -> None:
        tc = self._tcs[self._spawn_count % len(self._tcs)]
        self._spawn_count += 1
        white_info, black_info = await self._game_infos()
        game = self._registry.create_game(
            white=Participant(bot=white_info, is_house=True, house=self._house_a),
            black=Participant(bot=black_info, is_house=True, house=self._house_b),
            time_control=tc,
        )
        task = await self._launcher.launch(game)  # returns the run_game task
        self._live[task] = game.id
        task.add_done_callback(self._on_finished)

    async def _game_infos(self) -> "tuple[BotInfo, BotInfo]":
        """The two house identities for a fresh game. With a rating_provider
        (production), refresh each side's rating from the DB so the live lobby view
        matches the persisted (finalizer-updated) rating instead of the static boot
        value (KAN-207); without one, use the house objects' own info unchanged."""
        a, b = self._house_a.info, self._house_b.info
        if self._rating_provider is None:
            return a, b
        ra = await self._rating_provider(a.id)
        rb = await self._rating_provider(b.id)
        if ra is not None:
            a = a.model_copy(update={"rating": ra})
        if rb is not None:
            b = b.model_copy(update={"rating": rb})
        return a, b

    def _on_finished(self, task: asyncio.Task) -> None:
        game_id = self._live.pop(task, None)
        if game_id is not None:
            self._registry.remove(game_id)  # durable record is in Postgres
        if self._closing:
            return
        # Can't await in a done-callback — schedule the refill as its own task.
        refill = asyncio.create_task(self._refill())
        self._refills.add(refill)
        refill.add_done_callback(self._refills.discard)
