"""KAN-61 out-of-process house bots — the config-gated wiring + the subprocess
supervisor, exercised WITHOUT a live server or the real SDK.

Two things are guarded here:
1. the flag defaults to False and the default wiring is the in-process ambient
   supervisor (a regression guard: the production deploy must be unchanged);
2. the `HouseBotClientSupervisor` actually spawns, monitors/respawns, and stops its
   subprocesses (using a trivial local sleeper script — no `engineroom`, no server).
"""

from __future__ import annotations

import asyncio
import sys
import textwrap

import pytest

from engine_room.app import create_app
from engine_room.config import settings
from engine_room.game.ambient import AmbientSupervisor
from engine_room.game.house_clients import (
    RUNNER_PATH,
    HouseBotClientSupervisor,
    HouseClientSpec,
    default_ambient_specs,
)

# asyncio_mode = "auto" (pyproject) runs the async tests; no per-test marker needed.


# --- flag default + wiring (regression guard) --------------------------------


def test_flag_defaults_to_false():
    assert settings.house_bots_out_of_process is False


def test_default_wiring_is_in_process_supervisor():
    app = create_app(ambient_games=2)
    assert isinstance(app.state.ambient_supervisor, AmbientSupervisor)
    assert app.state.house_client_supervisor is None


def test_flag_on_wires_out_of_process_supervisor():
    async def fake_provider(spec):
        return "crbk_fake"

    app = create_app(
        ambient_games=2,
        house_bots_out_of_process=True,
        house_bot_ws_url="ws://127.0.0.1:8001/api/bot/v1",
        house_bot_key_provider=fake_provider,
    )
    assert app.state.ambient_supervisor is None
    assert isinstance(app.state.house_client_supervisor, HouseBotClientSupervisor)


def test_no_ambient_means_neither_supervisor():
    app = create_app(ambient_games=0, house_bots_out_of_process=True)
    assert app.state.ambient_supervisor is None
    assert app.state.house_client_supervisor is None


def test_default_specs_are_the_two_ambient_residents():
    specs = default_ambient_specs(depth=3, time_control=(180, 0))
    assert [s.name for s in specs] == ["jian-bot-001", "jian-bot-002"]
    assert all(s.time_control == (180, 0) for s in specs)


def test_runner_script_exists():
    assert RUNNER_PATH.is_file(), f"missing SDK runner at {RUNNER_PATH}"


# --- subprocess supervision (no server, no SDK) ------------------------------


@pytest.fixture
def sleeper(tmp_path):
    """A trivial runner substitute: sleeps forever, ignoring the CLI args the
    supervisor passes. Lets us exercise spawn/monitor/stop without the real SDK."""
    script = tmp_path / "sleeper.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys, time
            # ignore argv (--engine/--depth/--base/--inc); just stay alive
            time.sleep(300)
            """
        )
    )
    return script


def _specs():
    return [
        HouseClientSpec("bot_a", "a", "random", 1, (5, 0)),
        HouseClientSpec("bot_b", "b", "random", 1, (5, 0)),
    ]


async def test_supervisor_spawns_and_stops(sleeper):
    keys: list[str] = []

    async def provider(spec):
        keys.append(spec.bot_id)
        return f"crbk_{spec.bot_id}"

    sup = HouseBotClientSupervisor(
        _specs(),
        "ws://127.0.0.1:9/api/bot/v1",
        key_provider=provider,
        runner_path=sleeper,
        restart_backoff_seconds=0.05,
        poll_interval_seconds=0.05,
    )
    await sup.start()
    try:
        assert set(sup.pids) == {"bot_a", "bot_b"}  # both spawned
        assert set(keys) == {"bot_a", "bot_b"}  # key provisioned per identity
        assert all(p.poll() is None for p in sup._procs.values())  # alive
    finally:
        await sup.stop()
    assert sup.pids == {}  # all terminated


async def test_supervisor_respawns_a_dead_subprocess(sleeper):
    async def provider(spec):
        return f"crbk_{spec.bot_id}"

    sup = HouseBotClientSupervisor(
        _specs(),
        "ws://127.0.0.1:9/api/bot/v1",
        key_provider=provider,
        runner_path=sleeper,
        restart_backoff_seconds=0.05,
        poll_interval_seconds=0.05,
    )
    await sup.start()
    try:
        first = sup.pids["bot_a"]
        sup._procs["bot_a"].kill()  # simulate a crashed client
        # Wait for the monitor to notice, back off, and respawn.
        for _ in range(100):
            await asyncio.sleep(0.05)
            if sup.pids.get("bot_a") not in (None, first):
                break
        assert sup.pids["bot_a"] != first  # a fresh subprocess replaced it
        assert len(sup.pids) == 2
    finally:
        await sup.stop()


def test_supervisor_uses_current_interpreter_by_default(sleeper):
    sup = HouseBotClientSupervisor(
        _specs(), "ws://x", key_provider=lambda s: None, runner_path=sleeper
    )
    assert sup._python == sys.executable
