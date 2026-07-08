"""Elo widening-window arithmetic (ADR-0011 / ADR-0016 E8) — pure, unit-tested.

A ticket's acceptable rating gap starts narrow and widens with wait time, then
uncaps ("closest available / anyone", ADR-0011) — the honest form of Elo pairing
at low volume. Ratings are read-only in V3 (updates are V5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ticket import Ticket


@dataclass(frozen=True)
class Windowing:
    """The widening schedule (E8 defaults): half-width starts at ±`start`, grows
    by `step` every `step_seconds`, and is uncapped (∞) after `uncap_after_seconds`."""

    start: int = 100
    step: int = 100
    step_seconds: float = 10.0
    uncap_after_seconds: float = 60.0

    def half_width(self, waited_s: float) -> float:
        """Acceptable ±rating gap for a ticket that has waited `waited_s`.

        0–9s→100, 10–19s→200, … 50–59s→600, ≥60s→∞ (with the E8 defaults)."""
        if waited_s >= self.uncap_after_seconds:
            return math.inf
        steps = int(max(0.0, waited_s) // self.step_seconds)
        return float(self.start + self.step * steps)

    def uncapped(self, ticket: "Ticket", now: float) -> bool:
        return (now - ticket.enqueued_at) >= self.uncap_after_seconds

    def rating_gap_ok(self, a: "Ticket", b: "Ticket", now: float) -> bool:
        """True if a and b are close enough for *either* side's current window
        (max ⇒ pairs sooner, friendlier at low volume)."""
        wa = self.half_width(now - a.enqueued_at)
        wb = self.half_width(now - b.enqueued_at)
        return abs(a.rating - b.rating) <= max(wa, wb)
