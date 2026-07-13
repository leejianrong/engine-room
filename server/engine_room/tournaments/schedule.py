"""Round-robin scheduling — the standard *circle method* (pure logic).

Everyone plays everyone exactly once. For an even field of `n` players there are
`n - 1` rounds of `n / 2` games; for an odd field a bye marker is added so each
round one player sits out (a `bye`), giving `n` rounds. Colors alternate by round
so the field is roughly balanced between White and Black.

Kept dependency-free and deterministic so it is thoroughly unit-testable
independent of the DB / manager.
"""

from __future__ import annotations

from typing import Optional

# A pairing is (white, black); a bye is a pairing where exactly one side is None.
Pairing = tuple[Optional[str], Optional[str]]


def round_robin_schedule(players: list[str]) -> list[list[Pairing]]:
    """Return the full schedule as a list of rounds; each round is a list of
    `(white, black)` pairings. With an odd field, one pairing per round is a bye
    (one side is None). Order within `players` is the seeding used for rotation.

    Fewer than two players yields an empty schedule (nothing to play)."""
    field: list[Optional[str]] = list(players)
    if len(field) < 2:
        return []
    if len(field) % 2 == 1:
        field.append(None)  # odd → a bye sentinel sits opposite one player each round

    n = len(field)
    half = n // 2
    rounds: list[list[Pairing]] = []
    arr = field[:]
    for r in range(n - 1):
        pairs: list[Pairing] = []
        for i in range(half):
            p1 = arr[i]
            p2 = arr[n - 1 - i]
            # Alternate which of the two takes White by round, for color balance.
            pairs.append((p1, p2) if r % 2 == 0 else (p2, p1))
        rounds.append(pairs)
        # Rotate all but the first, moving the last into slot 1 (standard circle).
        arr = [arr[0], arr[-1], *arr[1:-1]]
    return rounds
