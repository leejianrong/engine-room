"""Spectator presence signal (KAN-209).

A tiny last-seen tracker that answers one question: *is anyone watching the
lobby right now?* It is bumped (`touch()`) by any spectator-facing read — a
`GET /api/games` lobby poll or an SSE watch-stream connect — and read
(`is_fresh()`) by the `AmbientSupervisor`, which only launches new ambient
house-vs-house games while presence is fresh (so we burn zero Neon/compute when
nobody is watching, ADR-0022 / KAN-209).

Rationale for counting lobby polls as presence: if no house game is running
there is nothing to spectate, so lobby *browsing* itself must be enough to
trigger games — otherwise the lobby would stay empty forever once it drains.

Single-process/in-memory (R5), like the rest of the ambient machinery. The
clock is injectable so the gating logic is deterministic under test (no
wall-clock sleeps)."""

from __future__ import annotations

import time
from typing import Callable, Optional


class Presence:
    def __init__(
        self,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = window_seconds
        self._clock = clock
        # None until the first spectator activity — a never-touched signal is
        # never fresh, so a freshly-booted server with no watchers launches no
        # ambient games until someone arrives.
        self._last_seen: Optional[float] = None

    def touch(self) -> None:
        """Record spectator activity now (a lobby poll or a watch connect)."""
        self._last_seen = self._clock()

    def is_fresh(self) -> bool:
        """True iff spectator activity was seen within the last `window` seconds."""
        if self._last_seen is None:
            return False
        return (self._clock() - self._last_seen) <= self._window
