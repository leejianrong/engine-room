"""TournamentManager — enrollment + running a round-robin (KAN-56).

Single-process, in-memory-orchestrated (like `EloMatchmaker`): started/stopped in
the app lifespan and held on `app.state`. Owns two background concerns:

- **enroll(session, tournament_id)** — a bot opting in via a tournament-tagged
  `seek`. Validates (exists, pending, not already in, not full), inserts a
  `tournament_entries` row, and — when the field reaches `target_size` —
  auto-starts the event. Returns an ack or a rejection (surfaced as an `error`
  with `INVALID_TOURNAMENT`, PROTOCOL §11), mirroring KAN-55's direct-challenge
  rejection shape.
- **run** — generate the circle-method schedule, persist every pairing (pending),
  then resolve them **sequentially** (one live game at a time, so no bot is ever
  in two tournament games at once), launching real games over the injected
  `GameLauncher` and writing standings back as each finishes. Mark the tournament
  `finished` when all pairings are resolved.

**Offline entrant policy (honest + simple):** a pairing is played only if BOTH
bots have a live WS session when it is due. If exactly one is offline, the online
side wins by **forfeit** (result recorded, `game_id` NULL — no real game). If both
are offline the pairing is **void** (no points). A **bye** (odd field) also scores
no points. Because games run sequentially and each entrant appears at most once per
round, a bot only needs to stay connected — it does not re-seek between its games.

Its own `session_factory` (default `SessionLocal`, injectable for tests) is used
for all writes here; the request-scoped REST reads use `get_async_session`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import func, select, update

from ..game.game import Participant
from ..ids import new_id
from ..persistence.db import SessionLocal
from ..persistence.models import Tournament, TournamentEntry, TournamentGame
from ..protocol.messages import TimeControl
from .schedule import round_robin_schedule

if TYPE_CHECKING:
    from ..game.registry import GameRegistry
    from ..matchmaking.launcher import GameLauncher
    from ..ws.session import Session
    from ..ws.session_registry import SessionRegistry

logger = logging.getLogger(__name__)


@dataclass
class EnrollResult:
    """Outcome of a tournament-seek enrollment. `error_code`/`error_message` set →
    the endpoint sends a non-fatal `error` (INVALID_TOURNAMENT) instead of a
    `seek_ack`; otherwise `seek_id` acks the enrollment (status 'enrolled')."""

    seek_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.error_code is None


class TournamentManager:
    def __init__(
        self,
        registry: "GameRegistry",
        session_registry: "SessionRegistry",
        launcher: "GameLauncher",
        session_factory=SessionLocal,
    ) -> None:
        self._registry = registry
        self._sessions = session_registry
        self._launcher = launcher
        self._sf = session_factory
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:  # nothing to run at rest (event-driven)
        return None

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    # --- enrollment ----------------------------------------------------------

    async def enroll(self, session: "Session", tournament_id: str) -> EnrollResult:
        bot_id = session.bot.id

        def reject(message: str) -> EnrollResult:
            return EnrollResult(error_code="INVALID_TOURNAMENT", error_message=message)

        autostart = False
        async with self._sf() as db:
            async with db.begin():
                t = await db.get(Tournament, tournament_id, with_for_update=True)
                if t is None:
                    return reject("no such tournament")
                if t.status != "pending":
                    return reject("tournament is not open for entry")
                count = await db.scalar(
                    select(func.count()).select_from(TournamentEntry).where(
                        TournamentEntry.tournament_id == tournament_id
                    )
                )
                already = await db.scalar(
                    select(TournamentEntry.id).where(
                        TournamentEntry.tournament_id == tournament_id,
                        TournamentEntry.bot_id == bot_id,
                    )
                )
                if already is not None:
                    return reject("already entered")
                if count >= t.target_size:
                    return reject("tournament is full")
                db.add(
                    TournamentEntry(
                        id=new_id("tent"),
                        tournament_id=tournament_id,
                        bot_id=bot_id,
                        seed=count,
                        score=0.0,
                    )
                )
                autostart = (count + 1) >= t.target_size

        if autostart:
            self._spawn_run(tournament_id)
        return EnrollResult(seek_id=new_id("seek"))

    # --- running -------------------------------------------------------------

    def _spawn_run(self, tournament_id: str) -> None:
        task = asyncio.create_task(self._guarded_run(tournament_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def start_tournament(self, tournament_id: str) -> bool:
        """Explicitly start a pending tournament (the REST start endpoint). Returns
        False if it is missing or not pending; True if a run was spawned."""
        async with self._sf() as db:
            t = await db.get(Tournament, tournament_id)
            if t is None or t.status != "pending":
                return False
        self._spawn_run(tournament_id)
        return True

    async def _guarded_run(self, tournament_id: str) -> None:
        try:
            await self._run(tournament_id)
        except Exception:  # a bad tournament must not take the app down
            logger.exception("tournament run failed", extra={"tournament_id": tournament_id})

    async def _run(self, tournament_id: str) -> None:
        # 1. Transition pending→running and persist the schedule atomically. The
        #    row lock + status guard make a double-start (auto + explicit) a no-op.
        async with self._sf() as db:
            async with db.begin():
                t = await db.get(Tournament, tournament_id, with_for_update=True)
                if t is None or t.status != "pending":
                    return
                entries = (
                    (
                        await db.execute(
                            select(TournamentEntry)
                            .where(TournamentEntry.tournament_id == tournament_id)
                            .order_by(TournamentEntry.seed)
                        )
                    )
                    .scalars()
                    .all()
                )
                tc = TimeControl(
                    base_seconds=t.base_seconds, increment_seconds=t.increment_seconds
                )
                schedule = round_robin_schedule([e.bot_id for e in entries])
                for rnd, pairs in enumerate(schedule):
                    for white, black in pairs:
                        is_bye = white is None or black is None
                        db.add(
                            TournamentGame(
                                id=new_id("tgame"),
                                tournament_id=tournament_id,
                                round=rnd,
                                white_bot_id=white,
                                black_bot_id=black,
                                result="bye" if is_bye else None,
                            )
                        )
                t.status = "running"
                t.started_at = datetime.now(timezone.utc)

        # 2. Resolve every pending (result IS NULL) pairing, in round then id order.
        async with self._sf() as db:
            pending = (
                (
                    await db.execute(
                        select(TournamentGame)
                        .where(
                            TournamentGame.tournament_id == tournament_id,
                            TournamentGame.result.is_(None),
                        )
                        .order_by(TournamentGame.round, TournamentGame.id)
                    )
                )
                .scalars()
                .all()
            )
            specs = [(g.id, g.white_bot_id, g.black_bot_id) for g in pending]

        for tgame_id, white_id, black_id in specs:
            result, game_id = await self._play_pairing(white_id, black_id, tc)
            await self._record_result(tgame_id, white_id, black_id, result, game_id)

        # 3. Done.
        async with self._sf() as db:
            async with db.begin():
                t = await db.get(Tournament, tournament_id, with_for_update=True)
                if t is not None and t.status == "running":
                    t.status = "finished"
                    t.finished_at = datetime.now(timezone.utc)

    async def _play_pairing(
        self, white_id: str, black_id: str, tc: TimeControl
    ) -> tuple[str, Optional[str]]:
        """Resolve one pairing. Returns (result, game_id). A real game runs only if
        both bots are connected; otherwise the absent side forfeits (game_id None),
        or the pairing is void if both are absent."""
        white_session = self._sessions.current(white_id)
        black_session = self._sessions.current(black_id)
        if white_session is None and black_session is None:
            return "void", None
        if white_session is None:
            return "black_wins", None  # white forfeits (offline)
        if black_session is None:
            return "white_wins", None  # black forfeits (offline)

        game = self._registry.create_game(
            white=Participant(bot=white_session.bot, session=white_session),
            black=Participant(bot=black_session.bot, session=black_session),
            time_control=tc,
        )
        task = await self._launcher.launch(game)
        result, _termination = await task
        return result, game.id

    async def _record_result(
        self,
        tgame_id: str,
        white_id: str,
        black_id: str,
        result: str,
        game_id: Optional[str],
    ) -> None:
        """Write the pairing's result + link, and add points to the standings
        (win=1, draw=0.5). void/aborted/bye score nothing."""
        async with self._sf() as db:
            async with db.begin():
                g = await db.get(TournamentGame, tgame_id)
                if g is None:
                    return
                g.result = result
                g.game_id = game_id
                awards: list[tuple[str, float]] = []
                if result == "white_wins":
                    awards.append((white_id, 1.0))
                elif result == "black_wins":
                    awards.append((black_id, 1.0))
                elif result == "draw":
                    awards.append((white_id, 0.5))
                    awards.append((black_id, 0.5))
                for bot_id, pts in awards:
                    await db.execute(
                        update(TournamentEntry)
                        .where(
                            TournamentEntry.tournament_id == g.tournament_id,
                            TournamentEntry.bot_id == bot_id,
                        )
                        .values(score=TournamentEntry.score + pts)
                    )
