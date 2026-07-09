"""V6 sub-step 4 (unit, DB-free): the AmbientSupervisor maintains N live
house-vs-house games, refills when one finishes, evicts the finished game from
the registry, and stops cleanly. The launcher is faked so the logic is
deterministic (no real games / no DB)."""

import asyncio

from engine_room.game.ambient import AmbientSupervisor, parse_pool
from engine_room.game.house_bots import (
    HOUSE_RANDOM_2_ID,
    HOUSE_RANDOM_2_NAME,
    RandomBot,
)
from engine_room.game.registry import GameRegistry
from engine_room.protocol.messages import TimeControl


class _FakeLauncher:
    """Stands in for GameLauncher: `launch` returns a task that stays pending
    until the test `finish()`es that game (like run_game ending)."""

    def __init__(self):
        self.launched: list[str] = []
        self._events: dict[str, asyncio.Event] = {}

    async def launch(self, game) -> asyncio.Task:
        self.launched.append(game.id)
        ev = asyncio.Event()
        self._events[game.id] = ev

        async def _run():
            await ev.wait()

        return asyncio.create_task(_run())

    def finish(self, game_id: str) -> None:
        self._events[game_id].set()


def _supervisor(reg, launcher, n):
    a = RandomBot()
    b = RandomBot(id=HOUSE_RANDOM_2_ID, name=HOUSE_RANDOM_2_NAME)
    return AmbientSupervisor(
        reg, launcher, a, b, n=n, time_control=TimeControl(base_seconds=180)
    )


def test_parse_pool():
    tc = parse_pool("180+0")
    assert (tc.base_seconds, tc.increment_seconds) == (180, 0)
    tc = parse_pool("300+2")
    assert (tc.base_seconds, tc.increment_seconds) == (300, 2)


async def test_supervisor_maintains_n_live_games():
    reg = GameRegistry()
    launcher = _FakeLauncher()
    sup = _supervisor(reg, launcher, n=2)
    await sup.start()
    assert len(launcher.launched) == 2
    assert len(reg.list_active()) == 2  # both house-vs-house games live
    await sup.stop()


async def test_supervisor_refills_and_evicts_on_finish():
    reg = GameRegistry()
    launcher = _FakeLauncher()
    sup = _supervisor(reg, launcher, n=2)
    await sup.start()
    finished = launcher.launched[0]

    launcher.finish(finished)
    for _ in range(10):  # let the done-callback + refill task run
        await asyncio.sleep(0)

    assert len(launcher.launched) == 3  # one replacement spawned
    assert reg.get(finished) is None  # finished game evicted from the registry
    assert len(reg.list_active()) == 2  # back to N live
    await sup.stop()


async def test_supervisor_disabled_when_zero():
    reg = GameRegistry()
    launcher = _FakeLauncher()
    sup = _supervisor(reg, launcher, n=0)
    await sup.start()
    assert launcher.launched == []
    await sup.stop()


async def test_stop_cancels_and_clears():
    reg = GameRegistry()
    launcher = _FakeLauncher()
    sup = _supervisor(reg, launcher, n=2)
    await sup.start()
    await sup.stop()
    # Cancelled games are removed from the registry (no refill while closing).
    assert reg.list_active() == []
