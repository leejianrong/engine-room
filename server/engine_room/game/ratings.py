"""Pure Elo rating math (ADR-0011 / 0016 E8) — no I/O.

Ratings move only when a Game reaches FINISHED (ADR-0010); the finalizer calls
these functions inside its single transaction (ADR-0025 #5) to compute each bot's
new rating from its current rating + rated-games count. Keeping the math pure
makes it trivially table-testable and keeps Elo out of the game loop and the DB
glue.

Not to be confused with `matchmaking/elo.py`, which is the *pairing window* (how
far apart two bots may be paired) — a different concern entirely.

Standard Elo:
    expected = 1 / (1 + 10 ** ((opp - rating) / 400))
    new      = round(rating + K * (score - expected))
with score = 1 (win) / 0.5 (draw) / 0 (loss), and K larger while a bot is
*provisional* (its first few rated games) so early ratings converge faster.
"""

from __future__ import annotations

# Defaults mirror ADR-0011 / 0016 E8; overridable via ER_ELO_* (config.py).
PROVISIONAL_K = 32
DEFAULT_K = 16
PROVISIONAL_GAMES = 30


def expected_score(rating: int, opponent: int) -> float:
    """Elo expected score of `rating` against `opponent` (in [0, 1])."""
    return 1.0 / (1.0 + 10.0 ** ((opponent - rating) / 400.0))


def k_factor(
    games_played: int,
    *,
    provisional_k: int = PROVISIONAL_K,
    default_k: int = DEFAULT_K,
    provisional_games: int = PROVISIONAL_GAMES,
) -> int:
    """The K-factor for a bot that has played `games_played` rated games: the
    larger provisional K for its first `provisional_games` games, else default."""
    return provisional_k if games_played < provisional_games else default_k


def updated(rating: int, opponent: int, score: float, k: int) -> int:
    """The bot's new (integer) rating after scoring `score` (1/0.5/0) against an
    opponent rated `opponent`, using K-factor `k`."""
    return round(rating + k * (score - expected_score(rating, opponent)))


def scores(result: str) -> tuple[float, float]:
    """(white_score, black_score) for a FINISHED `result` — win 1, draw 0.5,
    loss 0. Only called for decisive/draw results (never "aborted")."""
    if result == "white_wins":
        return 1.0, 0.0
    if result == "black_wins":
        return 0.0, 1.0
    return 0.5, 0.5  # draw
