"""Per-time-control pool eligibility + opponent selection (pure).

Encodes the two matchmaking constraints that operate *within* a pool:
- **Same-owner exclusion** (ADR-0016 H5): never pair two bots owned by the same
  user. House bots have `owner_id=None` and are exempt (ADR-0025 #1).
- **Soft anti-rematch** (ADR-0016 E5): skip a ticket's immediate previous
  opponent *only while another eligible opponent exists* (or until its window
  uncaps at 60s) — a hard cooldown would starve a 2-bot pool.

Elo proximity/widening lives in `elo.Windowing`. All functions take an explicit
`now` so widening/anti-rematch are deterministic in tests (D-d).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:
    from .elo import Windowing
    from .ticket import Ticket


def same_owner(a: "Ticket", b: "Ticket") -> bool:
    return a.owner_id is not None and a.owner_id == b.owner_id


def best_opponent(
    ticket: "Ticket",
    candidates: Iterable["Ticket"],
    now: float,
    windowing: "Windowing",
    *,
    excluded: frozenset[str] = frozenset(),
) -> Optional["Ticket"]:
    """The closest-rated eligible opponent for `ticket`, or None.

    Eligible = different owner, within the Elo window (either side). Ties broken
    by oldest ticket (`enqueued_at`). `excluded` is the anti-rematch set (bot ids
    of immediate previous opponents); it is honored only while an alternative
    exists (soft rule) and ignored entirely once `ticket`'s window has uncapped.
    """
    cands = list(candidates)

    def scan(honor_exclusion: bool) -> Optional["Ticket"]:
        best: Optional["Ticket"] = None
        best_gap = 0
        for c in cands:
            if c is ticket or same_owner(ticket, c):
                continue
            if not windowing.rating_gap_ok(ticket, c, now):
                continue
            if honor_exclusion and c.bot_id in excluded:
                continue
            gap = abs(ticket.rating - c.rating)
            if best is None or gap < best_gap or (
                gap == best_gap and c.enqueued_at < best.enqueued_at
            ):
                best, best_gap = c, gap
        return best

    honor = not windowing.uncapped(ticket, now)
    match = scan(honor_exclusion=honor)
    # Soft anti-rematch: if honoring the exclusion left no opponent, lift it (the
    # "only while another eligible opponent exists" clause, ADR-0016 E5).
    if match is None and honor:
        match = scan(honor_exclusion=False)
    return match
