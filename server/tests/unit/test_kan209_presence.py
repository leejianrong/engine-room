"""KAN-209 (unit, DB-free): spectator-gated ambient feeder.

Two layers, both deterministic (an injected clock — no wall-clock sleeps):
- the `Presence` last-seen signal, and
- the `AmbientSupervisor` gating on it (only launch new games while a spectator
  is present; drain when they leave; cold-start when they return), plus the two
  spectator endpoints bumping the signal.

The launcher is faked (as in test_v6_ambient) so the supervisor logic is pure."""

import asyncio

import httpx

from engine_room.app import create_app
from engine_room.game import ambient as ambient_mod
from engine_room.game.ambient import AmbientSupervisor
from engine_room.game.house_bots import (
    JIAN_001_ID,
    JIAN_001_NAME,
    JIAN_002_ID,
    JIAN_002_NAME,
    RandomBot,
)
from engine_room.game.registry import GameRegistry
from engine_room.protocol.messages import TimeControl
from engine_room.spectate.presence import Presence


class _Clock:
    """A hand-cranked monotonic clock — advance it to make presence go stale."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeLauncher:
    """Same seam as test_v6_ambient: launch() returns a task pending until the
    test finish()es the game."""

    def __init__(self) -> None:
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


def _supervisor(
    reg, launcher, presence, *, n=2, poll_interval_seconds=5.0, spawn_stagger_seconds=0.0
):
    a = RandomBot(id=JIAN_001_ID, name=JIAN_001_NAME)
    b = RandomBot(id=JIAN_002_ID, name=JIAN_002_NAME)
    return AmbientSupervisor(
        reg,
        launcher,
        a,
        b,
        n=n,
        time_controls=[TimeControl(base_seconds=180)],
        presence=presence,
        poll_interval_seconds=poll_interval_seconds,
        spawn_stagger_seconds=spawn_stagger_seconds,
    )


# --- Presence signal ---------------------------------------------------------


def test_presence_never_touched_is_not_fresh():
    clock = _Clock()
    p = Presence(60.0, clock=clock)
    assert p.is_fresh() is False  # a freshly-booted server has no watchers


def test_presence_fresh_within_window_stale_after():
    clock = _Clock()
    p = Presence(60.0, clock=clock)
    p.touch()
    assert p.is_fresh() is True
    clock.advance(59.9)
    assert p.is_fresh() is True  # still inside the window
    clock.advance(0.2)  # now 60.1s since touch
    assert p.is_fresh() is False  # gone stale
    p.touch()  # a fresh poll revives it
    assert p.is_fresh() is True


# --- Supervisor gating -------------------------------------------------------


async def test_no_new_games_while_no_spectator():
    """Stale (never-touched) presence at start → zero games launch."""
    reg, launcher, clock = GameRegistry(), _FakeLauncher(), _Clock()
    presence = Presence(60.0, clock=clock)  # never touched → stale
    sup = _supervisor(reg, launcher, presence, poll_interval_seconds=0)
    await sup.start()
    assert launcher.launched == []
    assert reg.list_active() == []
    await sup.stop()


async def test_launches_while_spectator_present():
    reg, launcher, clock = GameRegistry(), _FakeLauncher(), _Clock()
    presence = Presence(60.0, clock=clock)
    presence.touch()  # a spectator is here
    sup = _supervisor(reg, launcher, presence, n=2, poll_interval_seconds=0)
    await sup.start()
    assert len(launcher.launched) == 2
    assert len(reg.list_active()) == 2
    await sup.stop()


async def test_drains_when_spectator_leaves_without_aborting_live_games():
    """Present at start (2 live). Spectator leaves (presence goes stale). A game
    finishing is NOT replaced — the pool drains — and the still-live game is left
    running (never aborted)."""
    reg, launcher, clock = GameRegistry(), _FakeLauncher(), _Clock()
    presence = Presence(60.0, clock=clock)
    presence.touch()
    sup = _supervisor(reg, launcher, presence, n=2, poll_interval_seconds=0)
    await sup.start()
    assert len(reg.list_active()) == 2

    clock.advance(120)  # spectator gone > window → stale
    finished = launcher.launched[0]
    launcher.finish(finished)
    for _ in range(10):  # let the done-callback + refill task run
        await asyncio.sleep(0)

    assert len(launcher.launched) == 2  # NO replacement spawned
    assert reg.get(finished) is None  # finished game evicted
    assert len(reg.list_active()) == 1  # the other game is left running
    await sup.stop()


async def test_cold_start_refills_when_spectator_returns():
    """Booted with no spectator (0 games). A spectator arrives; the next poll tick
    (simulated by calling _refill, exactly what the poll loop does) fills the
    lobby — the KAN-209 cold-start."""
    reg, launcher, clock = GameRegistry(), _FakeLauncher(), _Clock()
    presence = Presence(60.0, clock=clock)  # stale
    sup = _supervisor(reg, launcher, presence, n=2, poll_interval_seconds=0)
    await sup.start()
    assert launcher.launched == []  # nothing while empty

    presence.touch()  # a spectator arrives
    await sup._refill()  # what the poll loop does on its next tick
    assert len(launcher.launched) == 2
    assert len(reg.list_active()) == 2
    await sup.stop()


async def test_poll_loop_cold_starts_the_lobby():
    """End-to-end cold-start through the real poll loop (tiny interval), not by
    calling _refill directly — proves the background loop refills on arrival."""
    reg, launcher, clock = GameRegistry(), _FakeLauncher(), _Clock()
    presence = Presence(60.0, clock=clock)
    sup = _supervisor(reg, launcher, presence, n=2, poll_interval_seconds=0.01)
    await sup.start()
    assert launcher.launched == []

    presence.touch()
    for _ in range(200):  # ~2s budget; loop tick is 10ms
        await asyncio.sleep(0.01)
        if len(reg.list_active()) == 2:
            break
    assert len(reg.list_active()) == 2
    await sup.stop()


async def test_presence_none_is_always_on():
    """Backward compat: no presence signal → the pre-KAN-209 always-on behaviour
    (the DB-free/integration tests drive the supervisor this way)."""
    reg, launcher = GameRegistry(), _FakeLauncher()
    sup = _supervisor(reg, launcher, presence=None, n=2, poll_interval_seconds=0)
    await sup.start()
    assert len(launcher.launched) == 2
    assert sup._poll_task is None  # no poll loop without a presence signal
    await sup.stop()


# --- Cold-start stagger (KAN-209 e2e regression) -----------------------------
# A multi-game cold-start must NOT spawn all n games back-to-back — that fires n
# simultaneous opening minimax searches (a GIL spike that starved the loop and
# broke the sdk.spec e2e). Deterministic: asyncio.sleep is stubbed to RECORD the
# requested gaps but still yield to the loop (via the captured real sleep(0)), so
# no wall-clock time passes and background tasks still run.


def _record_sleeps(monkeypatch) -> list[float]:
    """Patch asyncio.sleep to record non-zero gaps (the stagger) and yield via the
    real sleep(0). Zero-gap yields (used to drain callbacks) aren't recorded."""
    real_sleep = asyncio.sleep
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        if seconds:
            sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(ambient_mod.asyncio, "sleep", fake_sleep)
    return sleeps


async def test_cold_start_staggers_spawns(monkeypatch):
    reg, launcher, clock = GameRegistry(), _FakeLauncher(), _Clock()
    presence = Presence(60.0, clock=clock)
    presence.touch()
    sleeps = _record_sleeps(monkeypatch)
    sup = _supervisor(
        reg, launcher, presence, n=3, poll_interval_seconds=0, spawn_stagger_seconds=2.0
    )
    await sup._refill()  # what the cold-start poll tick does
    assert len(launcher.launched) == 3  # all n eventually launched
    # A gap BETWEEN each pair of spawns, none after the last (3 spawns → 2 gaps).
    assert sleeps == [2.0, 2.0]
    await sup.stop()


async def test_no_stagger_spawns_back_to_back(monkeypatch):
    """Default (0) → no inter-spawn sleep, preserving the always-on behaviour the
    integration/DB-free tests rely on."""
    reg, launcher, clock = GameRegistry(), _FakeLauncher(), _Clock()
    presence = Presence(60.0, clock=clock)
    presence.touch()
    sleeps = _record_sleeps(monkeypatch)
    sup = _supervisor(reg, launcher, presence, n=2, poll_interval_seconds=0)
    await sup._refill()
    assert len(launcher.launched) == 2
    assert sleeps == []  # no stagger
    await sup.stop()


async def test_single_respawn_does_not_stagger(monkeypatch):
    """A normal one-game respawn (pool at n-1) spawns exactly one game and never
    sleeps, even with a stagger configured — the gap only bites a multi-spawn
    cold-start."""
    reg, launcher, clock = GameRegistry(), _FakeLauncher(), _Clock()
    presence = Presence(60.0, clock=clock)
    presence.touch()
    sleeps = _record_sleeps(monkeypatch)
    sup = _supervisor(
        reg, launcher, presence, n=2, poll_interval_seconds=0, spawn_stagger_seconds=2.0
    )
    await sup.start()  # cold-start: 2 spawns → 1 gap
    assert sleeps == [2.0]

    sleeps.clear()
    launcher.finish(launcher.launched[0])  # one finishes → single refill
    for _ in range(10):
        await asyncio.sleep(0)  # yields (recorded as 0 → filtered), drains callbacks
    assert len(launcher.launched) == 3  # replacement spawned
    assert sleeps == []  # single respawn → no trailing stagger
    await sup.stop()


# --- Endpoints bump the signal ----------------------------------------------


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_lobby_poll_touches_presence():
    app = create_app()  # presence is always wired
    assert app.state.presence.is_fresh() is False  # nobody yet
    async with await _client(app) as client:
        resp = await client.get("/api/games")
    assert resp.status_code == 200
    assert app.state.presence.is_fresh() is True  # the poll counted as presence


async def test_watch_connect_touches_presence():
    app = create_app()
    reg = app.state.game_registry
    # A watch connect on an unknown game still bumps presence before the 404
    # (the touch happens on connect, which is the spectator-arrival signal).
    assert reg.get("nope") is None
    assert app.state.presence.is_fresh() is False
    async with await _client(app) as client:
        resp = await client.get("/api/spectate/nope")
    assert resp.status_code == 404
    assert app.state.presence.is_fresh() is True
