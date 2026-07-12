"""KAN-57: bullet (1+0) + the increment path.

Bullet is exposed as a real pool (greeter-served + in the ambient rotation — see
test_v6_ambient / test_v3_protocol_config). Here we pin the two clock behaviours
the ticket cares about, driven at the unit level with NO reliance on wall-clock
timing:

1. `Clock.credit_increment` actually adds the increment after a move — proven
   both directly on the clock and end-to-end through `run_game` (the mover's
   post-move clock exceeds its base because the increment dwarfs the ~0ms an
   instant house move is charged).
2. A short (bullet / 1-second) base clock keeps the deadline/charge math and the
   flag-on-timeout ("reaping") path safe: no negative deadline, remaining clamps
   at 0, and a full game runs to a terminal without error.
"""

import chess

from engine_room.channels import game_channel
from engine_room.game.clock import Clock
from engine_room.game.game import Participant
from engine_room.game.house_bots import RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import run_game
from engine_room.protocol.messages import TimeControl
from engine_room.pubsub.inproc import InProcPubSub


def test_credit_increment_adds_to_clock():
    """The dormant increment path (clock.py), driven directly: charge a turn's
    elapsed, then credit the increment — the remaining time goes up by exactly the
    increment. This is what worker.py does after every move (inc_ms was just 0 in
    every +0 pool before KAN-57 exposed increment-bearing controls)."""
    clock = Clock(60_000, 60_000)  # bullet-ish: 60s each
    clock.charge(chess.WHITE, 500)
    assert clock.remaining_ms(chess.WHITE) == 59_500
    clock.credit_increment(chess.WHITE, 2_000)  # a "+2" increment control
    assert clock.remaining_ms(chess.WHITE) == 61_500  # 59_500 + 2_000


def test_short_clock_math_and_reaping_are_safe():
    """A 1-second base clock (the shortest bullet extreme) keeps the worker's
    `wait_for`-timeout math sane: the deadline never goes negative, and an
    overspend clamps remaining to 0 → the next turn's deadline is 0.0, i.e. an
    immediate flag (the reaping path), not a negative timeout."""
    clock = Clock(1_000, 1_000)
    assert clock.deadline_s(chess.WHITE) == 1.0  # 1000ms -> 1.0s wait_for timeout
    clock.charge(chess.WHITE, 1_500)  # moved slower than the whole clock
    assert clock.remaining_ms(chess.WHITE) == 0  # clamped, never negative
    assert clock.deadline_s(chess.WHITE) == 0.0  # next turn flags immediately


async def _run_house_game(tc: TimeControl):
    pubsub = InProcPubSub()
    registry = GameRegistry()
    h1 = RandomBot(id="bot_h1", name="alice")
    h2 = RandomBot(id="bot_h2", name="bob")
    game = registry.create_game(
        white=Participant(bot=h1.info, is_house=True, house=h1),
        black=Participant(bot=h2.info, is_house=True, house=h2),
        time_control=tc,
    )
    sub = pubsub.subscribe(game_channel(game.id))
    result, termination = await run_game(game, pubsub)  # instant house moves
    events = []
    while True:
        ev = await sub.get()
        events.append(ev)
        if ev["type"] == "game_over":
            break
    return result, termination, events


async def test_worker_credits_increment_after_move():
    """End-to-end (worker.py + clock.py): in a 2+1 increment game, the mover's
    clock AFTER its move is higher than its base — only possible if the +1s
    increment was credited (an instant house move is charged ~0ms, far less than
    the 1000ms increment). Robust without timing: we assert `> base`, not an exact
    value."""
    tc = TimeControl(base_seconds=120, increment_seconds=1)  # 2+1
    _, _, events = await _run_house_game(tc)
    moves = [e for e in events if e["type"] == "move"]
    assert moves, "expected at least one move"
    base_ms = 120_000
    first = moves[0]  # White's first move (ply 0)
    assert first["to_move"] == "black"  # White has moved
    assert first["clocks"]["white_ms"] > base_ms  # base - ~0 + 1000 increment
    assert first["clocks"]["black_ms"] == base_ms  # Black hasn't moved yet


async def test_bullet_game_runs_to_completion():
    """A real bullet game on a tiny base clock plays to a natural terminal without
    error — confirms the short-clock path is exercised end-to-end, not just in the
    unit clock test above. (Instant house moves are charged ~0ms, so the game
    reaches a chess terminal rather than flagging.)"""
    tc = TimeControl(base_seconds=1)  # 1-second base, the bullet extreme
    result, termination, events = await _run_house_game(tc)
    assert events[0]["type"] == "game_start"
    assert events[-1]["type"] == "game_over"
    assert result in {"white_wins", "black_wins", "draw"}
    assert termination  # a real termination reason was assigned
