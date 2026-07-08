"""Sub-step 5: SessionRegistry newest-wins logic (pure, no sockets)."""

from types import SimpleNamespace

from engine_room.protocol.messages import BotInfo
from engine_room.ws.session_registry import SessionRegistry


def _session(bot_id: str):
    # A Session stand-in: the registry only touches `.bot.id`.
    return SimpleNamespace(bot=BotInfo(id=bot_id, name=bot_id, rating=1200))


def test_register_returns_replaced_session():
    reg = SessionRegistry()
    s1 = _session("bot_a")
    assert reg.register(s1) is None  # first session, nothing replaced
    s2 = _session("bot_a")
    assert reg.register(s2) is s1  # newest-wins: returns the one it displaced
    assert reg.current("bot_a") is s2


def test_distinct_bots_do_not_collide():
    reg = SessionRegistry()
    a, b = _session("bot_a"), _session("bot_b")
    assert reg.register(a) is None
    assert reg.register(b) is None
    assert reg.current("bot_a") is a
    assert reg.current("bot_b") is b


def test_remove_if_current_ignores_superseded_session():
    reg = SessionRegistry()
    old = _session("bot_a")
    new = _session("bot_a")
    reg.register(old)
    reg.register(new)  # new replaces old
    reg.remove_if_current(old)  # old's cleanup must NOT evict new
    assert reg.current("bot_a") is new
    reg.remove_if_current(new)
    assert reg.current("bot_a") is None


def test_evict_removes_and_returns():
    reg = SessionRegistry()
    s = _session("bot_a")
    reg.register(s)
    assert reg.evict("bot_a") is s
    assert reg.current("bot_a") is None
    assert reg.evict("bot_a") is None
