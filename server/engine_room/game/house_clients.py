"""Out-of-process house bots (KAN-61) — supervise the permanent ambient residents
as EXTERNAL `engineroom` SDK WebSocket clients.

This is the config-gated alternative to the in-process `AmbientSupervisor`
(``ER_HOUSE_BOTS_OUT_OF_PROCESS=true``). Instead of moving house pieces in-process,
it launches one **subprocess per house identity** running the SDK-based runner
(``sdk/house_bots/runner.py``); each subprocess connects back to this server's own
bot WS endpoint, authenticates with a real ``crbk_`` key, and seeks a game. The two
ambient residents (jian-bot-001 / jian-bot-002) share a time-control pool, so the
matcher pairs them with each other — a real, persisted, rated house-vs-house game
that also dogfoods the SDK end to end.

ADR-0021 decoupling: **this module never imports `engineroom`.** The SDK runs only
across the process boundary; the server merely spawns + supervises subprocesses
(`sys.executable <runner> ...`) and provisions their keys. The import-boundary is
verified by the SDK's own AST scan (SDK side) and by the server's import-hygiene
guard (`pytest --collect-only`).

Self-connect timing (ADR-0025 #3): the subprocesses dial back into *this* server,
which isn't accepting connections until uvicorn finishes startup. Spawning is
non-blocking (we never await a self-connection in the lifespan), and the SDK client
retries/backoff-connects, so a subprocess launched before the socket is up simply
reconnects once it is. A subprocess that dies is respawned by the monitor with a
fresh key + backoff.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from ..bots.keys import generate_key
from ..persistence.db import SessionLocal
from ..persistence.models import Bot
from .house_bots import (
    JIAN_001_ID,
    JIAN_001_NAME,
    JIAN_002_ID,
    JIAN_002_NAME,
)

logger = logging.getLogger(__name__)

# The SDK-based runner executed by each subprocess. It lives under `sdk/` (SDK
# territory) and is a legitimate SDK client run out-of-process — the server only
# references it as a file path, never imports it.
RUNNER_PATH = (
    Path(__file__).resolve().parents[3] / "sdk" / "house_bots" / "runner.py"
)

# An async key provider mints/returns the `crbk_` plaintext for a house identity.
KeyProvider = Callable[["HouseClientSpec"], Awaitable[str]]


@dataclass
class HouseClientSpec:
    """One out-of-process house identity to run as an SDK client."""

    bot_id: str
    name: str
    engine: str = "minimax"  # "minimax" | "random" (SDK reference bots)
    depth: int = 3
    time_control: tuple[int, int] = (180, 0)


def default_ambient_specs(*, depth: int, time_control: tuple[int, int]) -> list[HouseClientSpec]:
    """The two permanent ambient residents as SDK-client specs. They share a pool
    so the matcher pairs them with each other (house-vs-house)."""
    return [
        HouseClientSpec(JIAN_001_ID, JIAN_001_NAME, "minimax", depth, time_control),
        HouseClientSpec(JIAN_002_ID, JIAN_002_NAME, "minimax", depth, time_control),
    ]


def make_db_key_provider(session_factory=SessionLocal) -> KeyProvider:
    """Provision keys by minting a fresh `crbk_` for each house row and persisting
    its HMAC hash (production path). This is a *data* write on rows that already
    exist (migration 0005) — no schema change. Re-minting each boot effectively
    rotates the house key, which is fine (house bots aren't shown a key once)."""

    async def _provider(spec: HouseClientSpec) -> str:
        plaintext, key_hash, key_prefix = generate_key()
        async with session_factory() as session:
            bot = await session.get(Bot, spec.bot_id)
            if bot is None:
                raise RuntimeError(
                    f"house bot row {spec.bot_id!r} missing — run migrations "
                    "(0005 seeds the house identities) before enabling "
                    "ER_HOUSE_BOTS_OUT_OF_PROCESS."
                )
            bot.key_hash = key_hash
            bot.key_prefix = key_prefix
            bot.key_created_at = datetime.now(timezone.utc)
            await session.commit()
        return plaintext

    return _provider


class HouseBotClientSupervisor:
    """Launches + supervises the out-of-process house-bot SDK clients.

    Lifecycle mirrors `AmbientSupervisor` (``start()`` / ``stop()``), so the app
    lifespan drives either one uniformly. ``start()`` provisions each identity's
    key, spawns its subprocess, and starts a monitor task that respawns a dead
    subprocess (with a fresh key + backoff). ``stop()`` cancels the monitor and
    terminates the subprocesses.
    """

    def __init__(
        self,
        specs: Sequence[HouseClientSpec],
        url: str,
        *,
        key_provider: KeyProvider,
        runner_path: Path = RUNNER_PATH,
        python: str = sys.executable,
        restart_backoff_seconds: float = 1.0,
        poll_interval_seconds: float = 0.5,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self._specs = list(specs)
        self._url = url
        self._key_provider = key_provider
        self._runner_path = runner_path
        self._python = python
        self._restart_backoff = restart_backoff_seconds
        self._poll_interval = poll_interval_seconds
        self._extra_env = dict(extra_env or {})
        self._procs: dict[str, subprocess.Popen] = {}  # bot_id -> process
        self._specs_by_id = {s.bot_id: s for s in self._specs}
        self._monitor: asyncio.Task | None = None
        self._closing = False
        self._started = False

    async def start(self) -> None:
        if self._started or not self._specs:
            return
        self._started = True
        self._closing = False
        for spec in self._specs:
            await self._spawn(spec)
        self._monitor = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        self._closing = True
        if self._monitor is not None:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
            self._monitor = None
        for proc in self._procs.values():
            self._terminate(proc)
        self._procs.clear()
        self._started = False

    # --- internals -----------------------------------------------------------

    async def _spawn(self, spec: HouseClientSpec) -> None:
        try:
            key = await self._key_provider(spec)
        except Exception:
            logger.exception("could not provision key for house bot %s", spec.bot_id)
            return
        env = {
            **os.environ,
            **self._extra_env,
            "ENGINEROOM_KEY": key,
            "ENGINEROOM_URL": self._url,
        }
        cmd = [
            self._python,
            str(self._runner_path),
            "--engine",
            spec.engine,
            "--depth",
            str(spec.depth),
            "--base",
            str(spec.time_control[0]),
            "--inc",
            str(spec.time_control[1]),
        ]
        # Popen (not asyncio.create_subprocess_exec) so we don't depend on a child
        # watcher on the running loop; a light poll loop reaps + respawns instead.
        proc = subprocess.Popen(cmd, env=env)  # noqa: S603 - trusted args, no shell
        self._procs[spec.bot_id] = proc
        logger.info(
            "spawned out-of-process house bot %s (pid %s) → %s",
            spec.name,
            proc.pid,
            self._url,
        )

    async def _monitor_loop(self) -> None:
        while not self._closing:
            await asyncio.sleep(self._poll_interval)
            for bot_id, proc in list(self._procs.items()):
                if proc.poll() is None:
                    continue  # still running
                if self._closing:
                    return
                logger.warning(
                    "house bot %s exited (code %s); respawning", bot_id, proc.returncode
                )
                self._procs.pop(bot_id, None)
                await asyncio.sleep(self._restart_backoff)
                spec = self._specs_by_id.get(bot_id)
                if spec is not None and not self._closing:
                    await self._spawn(spec)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - slow child
            proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)

    # Test/introspection helpers.
    @property
    def pids(self) -> dict[str, int]:
        return {bot_id: p.pid for bot_id, p in self._procs.items()}
