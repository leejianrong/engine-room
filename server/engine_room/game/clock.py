"""Server-authoritative clock (ADR-0003). Per-seat remaining milliseconds.

The side-to-move's clock runs from the instant the server sends `your_turn`
to the instant it receives the move — the bot eats its own network latency.
The game loop (worker.py) measures elapsed with a monotonic source and calls
`charge`; a flag is detected when the mover fails to move within the deadline
(the loop's wait_for timing out). Increment (0 at MVP) is credited post-move.
"""

import chess


class Clock:
    def __init__(self, white_ms: int, black_ms: int):
        self._ms: dict[chess.Color, float] = {
            chess.WHITE: float(white_ms),
            chess.BLACK: float(black_ms),
        }

    def deadline_s(self, color: chess.Color) -> float:
        """Seconds the mover has left — the wait_for timeout for this turn."""
        return max(0.0, self._ms[color]) / 1000.0

    def charge(self, color: chess.Color, elapsed_ms: float) -> None:
        self._ms[color] -= elapsed_ms

    def credit_increment(self, color: chess.Color, increment_ms: int) -> None:
        self._ms[color] += increment_ms

    def remaining_ms(self, color: chess.Color) -> int:
        return int(max(0.0, self._ms[color]))
