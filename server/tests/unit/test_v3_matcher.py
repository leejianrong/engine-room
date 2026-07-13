"""V3 sub-step 4: EloMatchmaker.tick() behaviors (DB-free, no sockets, no sleep).

Drives the matcher against fake sessions + a fake launcher + a controllable
clock, so every time-driven rule (widening, TTL, greeter solo-wait) is exact."""

import pytest

from engine_room.game.game import Participant
from engine_room.game.house_bots import EPHRAIM_ID, RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.matchmaking.elo import Windowing
from engine_room.matchmaking.matcher import EloMatchmaker
from engine_room.protocol.messages import BotInfo, SeekEnded, TimeControl

TC_3 = TimeControl(base_seconds=180)   # "180+0" — greeter pool
TC_5 = TimeControl(base_seconds=300)   # "300+0" — no greeter


class FakeSession:
    def __init__(self, bot: BotInfo):
        self.bot = bot
        self.sent: list = []

    async def send(self, msg) -> None:
        self.sent.append(msg)


class FakeSessionRegistry:
    def __init__(self) -> None:
        self._cur: dict = {}

    def track(self, s: FakeSession) -> FakeSession:
        self._cur[s.bot.id] = s
        return s

    def drop(self, bot_id: str) -> None:
        self._cur.pop(bot_id, None)

    def current(self, bot_id: str):
        return self._cur.get(bot_id)


class FakeLauncher:
    def __init__(self) -> None:
        self.launched: list = []

    async def launch(self, game) -> None:
        self.launched.append(game)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _bot(bot_id, rating, owner=None):
    return BotInfo(id=bot_id, name=bot_id, rating=rating, owner_id=owner)


def _make(**kw):
    sreg = FakeSessionRegistry()
    launcher = FakeLauncher()
    clock = Clock()
    mm = EloMatchmaker(
        registry=GameRegistry(),
        session_registry=sreg,
        launcher=launcher,
        house_bot=RandomBot(),
        windowing=Windowing(),
        ticket_ttl_seconds=kw.get("ttl", 120.0),
        greeter_solo_wait_seconds=kw.get("greeter_wait", 3.0),
        greeter_pools=kw.get("greeter_pools", ("180+0",)),
        now=clock,
    )
    return mm, sreg, launcher, clock


async def _seek(mm, sreg, bot, tc):
    s = sreg.track(FakeSession(bot))
    result = await mm.seek(s, tc)
    return s, result.seek_id


async def test_two_close_reals_pair_by_elo():
    mm, sreg, launcher, clock = _make()
    await _seek(mm, sreg, _bot("bot_a", 1200, "uA"), TC_5)
    await _seek(mm, sreg, _bot("bot_b", 1210, "uB"), TC_5)
    await mm.tick()
    assert len(launcher.launched) == 1
    game = launcher.launched[0]
    assert {game.white.bot.id, game.black.bot.id} == {"bot_a", "bot_b"}
    assert game.white.bot.id == "bot_a"  # oldest ticket takes White


async def test_same_owner_never_paired():
    mm, sreg, launcher, clock = _make()
    await _seek(mm, sreg, _bot("bot_a", 1200, "uX"), TC_5)
    await _seek(mm, sreg, _bot("bot_b", 1200, "uX"), TC_5)  # same owner
    clock.t = 30
    await mm.tick()
    assert launcher.launched == []  # never pairs, even after widening


async def test_far_ratings_pair_only_after_widening():
    mm, sreg, launcher, clock = _make()
    await _seek(mm, sreg, _bot("bot_a", 1200, "uA"), TC_5)
    await _seek(mm, sreg, _bot("bot_b", 1500, "uB"), TC_5)  # gap 300
    clock.t = 5
    await mm.tick()
    assert launcher.launched == []       # window 100 < 300
    clock.t = 20
    await mm.tick()
    assert len(launcher.launched) == 1   # window 300 == 300 → pair


async def test_lonely_seek_expires_at_ttl():
    mm, sreg, launcher, clock = _make(ttl=10.0, greeter_pools=())
    session, seek_id = await _seek(mm, sreg, _bot("bot_a", 1200, "uA"), TC_5)
    clock.t = 5
    await mm.tick()
    assert session.sent == []            # still waiting
    clock.t = 10
    await mm.tick()
    ended = session.sent[-1]
    assert isinstance(ended, SeekEnded)
    assert ended.reason == "expired"
    assert ended.seek_id == seek_id


async def test_seek_cancel_ends_the_seek():
    mm, sreg, launcher, clock = _make()
    session, seek_id = await _seek(mm, sreg, _bot("bot_a", 1200, "uA"), TC_5)
    await mm.cancel(seek_id)
    ended = session.sent[-1]
    assert isinstance(ended, SeekEnded) and ended.reason == "cancelled"
    # A subsequent tick must not pair or re-touch the cancelled ticket.
    clock.t = 200
    await mm.tick()
    assert launcher.launched == []


async def test_greeter_fallback_after_solo_wait():
    mm, sreg, launcher, clock = _make(greeter_wait=3.0)
    await _seek(mm, sreg, _bot("bot_a", 1200, "uA"), TC_3)  # greeter pool
    clock.t = 1
    await mm.tick()
    assert launcher.launched == []       # not yet H
    clock.t = 3
    await mm.tick()
    assert len(launcher.launched) == 1
    game = launcher.launched[0]
    assert game.white.bot.id == "bot_a"
    assert game.black.is_house is True
    assert game.black.bot.id == EPHRAIM_ID


async def test_no_greeter_in_five_plus_zero():
    mm, sreg, launcher, clock = _make(greeter_wait=3.0)  # greeter only in 180+0
    await _seek(mm, sreg, _bot("bot_a", 1200, "uA"), TC_5)
    clock.t = 60
    await mm.tick()
    assert launcher.launched == []       # 5+0 has no greeter → keeps waiting


async def test_dead_session_reaped_before_pairing():
    mm, sreg, launcher, clock = _make(greeter_pools=())
    s_a, _ = await _seek(mm, sreg, _bot("bot_a", 1200, "uA"), TC_5)
    await _seek(mm, sreg, _bot("bot_b", 1200, "uB"), TC_5)
    sreg.drop("bot_a")  # bot A disconnected between seek and pairing
    await mm.tick()
    assert launcher.launched == []       # A reaped; B has no opponent, not paired


async def test_soft_anti_rematch_prefers_a_fresh_opponent():
    mm, sreg, launcher, clock = _make(greeter_pools=())
    # A and B just played (recorded as each other's previous opponent).
    mm._last_opponent["bot_a"] = "bot_b"
    mm._last_opponent["bot_b"] = "bot_a"
    await _seek(mm, sreg, _bot("bot_a", 1200, "uA"), TC_5)
    await _seek(mm, sreg, _bot("bot_b", 1200, "uB"), TC_5)
    await _seek(mm, sreg, _bot("bot_c", 1200, "uC"), TC_5)
    await mm.tick()
    # A should avoid an immediate rematch with B while C is available.
    ids = {(g.white.bot.id, g.black.bot.id) for g in launcher.launched}
    paired = {frozenset(p) for p in ids}
    assert frozenset({"bot_a", "bot_b"}) not in paired


# --- KAN-55 direct challenges -------------------------------------------------


def _track(sreg, bot):
    """Register a bot's live session (online) without enrolling a seek ticket."""
    return sreg.track(FakeSession(bot))


async def _challenge(mm, session, opponent_bot_id, tc=TC_3):
    return await mm.seek(session, tc, opponent_bot_id=opponent_bot_id)


async def test_direct_challenge_pairs_named_bot():
    mm, sreg, launcher, clock = _make()
    a = _track(sreg, _bot("bot_a", 1200, "uA"))
    _track(sreg, _bot("bot_b", 1800, "uB"))  # far rating — anon would not pair now
    result = await _challenge(mm, a, "bot_b")
    assert result.error is None
    assert result.status == "paired"
    game = result.game
    assert game is not None
    assert game.white.bot.id == "bot_a"  # challenger (initiator) takes White
    assert game.black.bot.id == "bot_b"
    # seek() itself does not launch — the endpoint launches result.game.
    assert launcher.launched == []


async def test_direct_challenge_vs_house_bot_allowed():
    mm, sreg, launcher, clock = _make()
    a = _track(sreg, _bot("bot_a", 1200, "uA"))
    _track(sreg, _bot("house_1", 1200, owner=None))  # house: owner None, exempt
    result = await _challenge(mm, a, "house_1")
    assert result.error is None and result.game is not None


async def test_direct_challenge_self_is_rejected():
    mm, sreg, launcher, clock = _make()
    a = _track(sreg, _bot("bot_a", 1200, "uA"))
    result = await _challenge(mm, a, "bot_a")
    assert result.game is None
    assert result.error is not None and result.error.code == "INVALID_CHALLENGE"


async def test_direct_challenge_offline_target_is_rejected():
    mm, sreg, launcher, clock = _make()
    a = _track(sreg, _bot("bot_a", 1200, "uA"))
    result = await _challenge(mm, a, "bot_ghost")
    assert result.game is None
    assert result.error is not None and result.error.code == "OPPONENT_UNAVAILABLE"


async def test_direct_challenge_same_owner_is_rejected():
    mm, sreg, launcher, clock = _make()
    a = _track(sreg, _bot("bot_a", 1200, "uX"))
    _track(sreg, _bot("bot_b", 1200, "uX"))  # same owner
    result = await _challenge(mm, a, "bot_b")
    assert result.game is None
    assert result.error is not None and result.error.code == "INVALID_CHALLENGE"


async def test_direct_challenge_busy_target_is_rejected():
    mm, sreg, launcher, clock = _make()
    a = _track(sreg, _bot("bot_a", 1200, "uA"))
    b = _track(sreg, _bot("bot_b", 1200, "uB"))
    # Put B in a live game (bound in the active-game index).
    game = mm._registry.create_game(
        white=Participant(bot=b.bot, session=b),
        black=Participant(bot=_bot("house_1", 1200, owner=None), is_house=True),
        time_control=TC_3,
    )
    mm._registry.bind_active(game)
    result = await _challenge(mm, a, "bot_b")
    assert result.game is None
    assert result.error is not None and result.error.code == "OPPONENT_UNAVAILABLE"


async def test_direct_challenge_drops_targets_waiting_ticket():
    mm, sreg, launcher, clock = _make()
    a = _track(sreg, _bot("bot_a", 1200, "uA"))
    # B is waiting in the anonymous queue; a direct challenge pulls it out so the
    # background matcher can't also pair it elsewhere.
    _, b_seek = await _seek(mm, sreg, _bot("bot_b", 1200, "uB"), TC_3)
    result = await _challenge(mm, a, "bot_b")
    assert result.error is None and result.game is not None
    assert b_seek not in mm._by_seek
    assert all(t.bot_id != "bot_b" for pool in mm._pools.values() for t in pool)
    # A later tick must not re-pair B (its ticket is gone).
    await mm.tick()
    assert launcher.launched == []


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
