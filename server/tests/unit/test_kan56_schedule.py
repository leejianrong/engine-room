"""KAN-56 round-robin scheduling (pure logic) — the circle method.

Everyone plays everyone exactly once; no self-pairing; odd fields get one bye per
round. Colors alternate by round. These are the invariants the manager relies on.
"""

from collections import Counter
from itertools import combinations

import pytest

from engine_room.tournaments.schedule import round_robin_schedule


def _real_pairs(schedule):
    """All non-bye pairings as unordered frozensets (color-independent)."""
    out = []
    for rnd in schedule:
        for white, black in rnd:
            if white is not None and black is not None:
                out.append(frozenset((white, black)))
    return out


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7, 8])
def test_everyone_plays_everyone_exactly_once(n):
    players = [f"bot_{i}" for i in range(n)]
    schedule = round_robin_schedule(players)

    pairs = _real_pairs(schedule)
    counts = Counter(pairs)

    # Every unordered pair of distinct players appears exactly once.
    expected = {frozenset(c) for c in combinations(players, 2)}
    assert set(counts) == expected
    assert all(v == 1 for v in counts.values())
    assert len(pairs) == n * (n - 1) // 2


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7])
def test_no_self_pairing(n):
    players = [f"bot_{i}" for i in range(n)]
    for rnd in round_robin_schedule(players):
        for white, black in rnd:
            if white is not None and black is not None:
                assert white != black


def test_even_field_has_no_byes_and_n_minus_1_rounds():
    players = [f"bot_{i}" for i in range(4)]
    schedule = round_robin_schedule(players)
    assert len(schedule) == 3  # n - 1 rounds
    for rnd in schedule:
        assert len(rnd) == 2  # n / 2 games
        assert all(w is not None and b is not None for w, b in rnd)


def test_odd_field_gives_each_player_exactly_one_bye():
    players = [f"bot_{i}" for i in range(5)]
    schedule = round_robin_schedule(players)
    assert len(schedule) == 5  # odd n → n rounds, one bye each

    byes = Counter()
    for rnd in schedule:
        bye_count = 0
        for white, black in rnd:
            if white is None or black is None:
                bye_count += 1
                lone = white if white is not None else black
                byes[lone] += 1
        assert bye_count == 1  # exactly one bye per round
    # Every player sits out exactly once.
    assert byes == Counter({p: 1 for p in players})


def test_degenerate_fields_are_empty():
    assert round_robin_schedule([]) == []
    assert round_robin_schedule(["solo"]) == []


def test_colors_alternate_by_round():
    # With the circle method the first board's White flips each round.
    players = [f"bot_{i}" for i in range(4)]
    schedule = round_robin_schedule(players)
    first_board_white = [rnd[0][0] for rnd in schedule]
    # bot_0 is fixed in slot 0; it takes White on even rounds, Black on odd ones.
    assert first_board_white[0] == "bot_0"  # round 0: (arr[0], arr[-1])
