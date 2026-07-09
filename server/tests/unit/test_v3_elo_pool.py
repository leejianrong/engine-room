"""V3 sub-step 2: pure Elo-window + pool-eligibility logic (DB-free, no sockets).

Drives the widening schedule, same-owner exclusion, closest-Elo selection, and
soft anti-rematch with an explicit `now`, so nothing sleeps."""

import math

from engine_room.matchmaking.elo import Windowing
from engine_room.matchmaking.pool import best_opponent, same_owner
from engine_room.matchmaking.ticket import Ticket, tc_key
from engine_room.protocol.messages import BotInfo, TimeControl


class _FakeSession:
    """Minimal stand-in for ws.Session — the matcher only reads `.bot`."""

    def __init__(self, bot: BotInfo):
        self.bot = bot


def _ticket(seek_id, *, rating, owner=None, enqueued_at=0.0, bot_id=None):
    bot = BotInfo(id=bot_id or seek_id, name=seek_id, rating=rating, owner_id=owner)
    tc = TimeControl(base_seconds=180)
    return Ticket(
        seek_id=seek_id,
        session=_FakeSession(bot),
        time_control=tc,
        tc_key=tc_key(tc),
        enqueued_at=enqueued_at,
    )


# --- Windowing (E8 schedule) --------------------------------------------------


def test_window_widening_schedule():
    w = Windowing()  # E8 defaults
    assert w.half_width(0) == 100
    assert w.half_width(9.9) == 100
    assert w.half_width(10) == 200
    assert w.half_width(25) == 300
    assert w.half_width(55) == 600
    assert w.half_width(60) == math.inf  # uncapped
    assert w.half_width(120) == math.inf


def test_rating_gap_uses_the_wider_of_the_two_windows():
    w = Windowing()
    a = _ticket("a", rating=1200, enqueued_at=0.0)   # fresh: window 100
    b = _ticket("b", rating=1500, enqueued_at=0.0)   # gap 300
    assert not w.rating_gap_ok(a, b, now=5)           # both windows 100 < 300
    assert not w.rating_gap_ok(a, b, now=15)          # both windows 200 < 300
    assert w.rating_gap_ok(a, b, now=20)              # windows 300 == 300 → pair


# --- same-owner (H5) ----------------------------------------------------------


def test_same_owner_excluded_house_exempt():
    a = _ticket("a", rating=1200, owner="user_x")
    b = _ticket("b", rating=1200, owner="user_x")
    c = _ticket("c", rating=1200, owner="user_y")
    house = _ticket("h", rating=1200, owner=None)
    assert same_owner(a, b) is True
    assert same_owner(a, c) is False
    assert same_owner(a, house) is False  # None owner never collides


def test_best_opponent_never_pairs_same_owner():
    w = Windowing()
    t = _ticket("t", rating=1200, owner="user_x")
    sib = _ticket("sib", rating=1200, owner="user_x")   # same owner → ineligible
    assert best_opponent(t, [sib], now=0, windowing=w) is None


# --- closest-Elo selection ----------------------------------------------------


def test_best_opponent_picks_closest_rating():
    w = Windowing()
    t = _ticket("t", rating=1200, owner="u0", enqueued_at=0)
    near = _ticket("near", rating=1180, owner="u1", enqueued_at=0)   # gap 20
    far = _ticket("far", rating=1150, owner="u2", enqueued_at=0)     # gap 50
    assert best_opponent(t, [far, near], now=5, windowing=w) is near


def test_best_opponent_tie_breaks_on_oldest_ticket():
    w = Windowing()
    t = _ticket("t", rating=1200, owner="u0")
    older = _ticket("older", rating=1250, owner="u1", enqueued_at=1.0)  # gap 50
    newer = _ticket("newer", rating=1150, owner="u2", enqueued_at=5.0)  # gap 50
    assert best_opponent(t, [newer, older], now=30, windowing=w) is older


# --- soft anti-rematch (E5) ---------------------------------------------------


def test_anti_rematch_skips_prev_opponent_when_alternative_exists():
    w = Windowing()
    t = _ticket("t", rating=1200, owner="u0")
    prev = _ticket("prev", rating=1200, owner="u1", bot_id="bot_prev")
    other = _ticket("other", rating=1200, owner="u2", bot_id="bot_other")
    chosen = best_opponent(
        t, [prev, other], now=5, windowing=w, excluded=frozenset({"bot_prev"})
    )
    assert chosen is other  # prev skipped, alternative taken


def test_anti_rematch_lifts_when_prev_is_the_only_option():
    w = Windowing()
    t = _ticket("t", rating=1200, owner="u0")
    prev = _ticket("prev", rating=1200, owner="u1", bot_id="bot_prev")
    # Only the previous opponent is present and window not yet uncapped → the soft
    # rule lifts the exclusion rather than starve the pool.
    chosen = best_opponent(
        t, [prev], now=5, windowing=w, excluded=frozenset({"bot_prev"})
    )
    assert chosen is prev
