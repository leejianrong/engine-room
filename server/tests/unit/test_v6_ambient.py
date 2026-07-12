"""V6 sub-step 4 (unit, DB-free): the AmbientSupervisor maintains N live
house-vs-house games, refills when one finishes, evicts the finished game from
the registry, and stops cleanly. The launcher is faked so the logic is
deterministic (no real games / no DB)."""

import asyncio

from engine_room.game.ambient import AmbientSupervisor, parse_pool
from engine_room.game.house_bots import (
    JIAN_001_ID,
    JIAN_001_NAME,
    JIAN_002_ID,
    JIAN_002_NAME,
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
    # Fast random movers with the permanent-bot identities (the supervisor logic
    # under test is mover-agnostic; production uses MinimaxBot).
    a = RandomBot(id=JIAN_001_ID, name=JIAN_001_NAME)
    b = RandomBot(id=JIAN_002_ID, name=JIAN_002_NAME)
    return AmbientSupervisor(
        reg, launcher, a, b, n=n, time_controls=[TimeControl(base_seconds=180)]
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


async def test_supervisor_rotates_time_controls():
    """KAN-57: with a rotation of pools the live games span all of them (round-
    robin across the N slots), so the lobby shows a mix (e.g. 3+0 + bullet)."""
    reg = GameRegistry()
    launcher = _FakeLauncher()
    a = RandomBot(id=JIAN_001_ID, name=JIAN_001_NAME)
    b = RandomBot(id=JIAN_002_ID, name=JIAN_002_NAME)
    sup = AmbientSupervisor(
        reg,
        launcher,
        a,
        b,
        n=2,
        time_controls=[TimeControl(base_seconds=180), TimeControl(base_seconds=60)],
    )
    await sup.start()
    bases = sorted(g.time_control.base_seconds for g in reg.list_active())
    assert bases == [60, 180]  # one bullet, one 3+0 — both rotation entries live
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


def test_house_bot_personas_pick_legal_moves():
    """The two personas: ephraim (RandomBot, easy) and jian (MinimaxBot)."""
    import chess

    from engine_room.game.house_bots import (
        EPHRAIM_ID,
        EPHRAIM_NAME,
        JIAN_001_NAME,
        MinimaxBot,
        RandomBot,
    )

    ephraim = RandomBot()  # defaults to the ephemeral greeter identity
    assert (ephraim.info.id, ephraim.info.name) == (EPHRAIM_ID, EPHRAIM_NAME)
    legal = {m.uci() for m in chess.Board().legal_moves}
    assert ephraim.choose_move(chess.Board()) in legal

    jian = MinimaxBot(depth=2)  # shallow keeps the unit test fast
    assert jian.info.name == JIAN_001_NAME
    assert jian.choose_move(chess.Board()) in legal
