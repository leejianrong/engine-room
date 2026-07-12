"""V3 sub-step 1 checkpoint: seek_cancel parses; matchmaking settings load."""

import pytest

from engine_room.config import Settings
from engine_room.protocol.messages import (
    ProtocolError,
    SeekCancel,
    SeekEnded,
    parse_client_message,
)


def test_parse_seek_cancel():
    msg = parse_client_message('{"type":"seek_cancel","seek_id":"seek_77"}')
    assert isinstance(msg, SeekCancel)
    assert msg.seek_id == "seek_77"


def test_seek_cancel_requires_seek_id():
    with pytest.raises(ProtocolError) as exc:
        parse_client_message('{"type":"seek_cancel"}')
    assert exc.value.code == "INVALID_MESSAGE"


def test_seek_ended_serializes_reason():
    ended = SeekEnded(seek_id="seek_77", reason="expired")
    assert ended.model_dump() == {
        "type": "seek_ended",
        "seek_id": "seek_77",
        "reason": "expired",
    }


def test_matchmaking_settings_defaults():
    s = Settings()
    assert s.mm_window_start == 100
    assert s.mm_window_step == 100
    assert s.mm_window_uncap_seconds == 60.0
    assert s.mm_ticket_ttl_seconds == 120.0
    # 3+0, bullet 1+0, and 2+1 increment are greeter-served (KAN-57); 5+0 has none.
    assert s.mm_greeter_pools == ["180+0", "60+0", "120+1"]


def test_matchmaking_settings_env_override(monkeypatch):
    monkeypatch.setenv("ER_MM_TICKET_TTL_SECONDS", "2.5")
    monkeypatch.setenv("ER_MM_GREETER_POOLS", '["300+0"]')
    s = Settings()
    assert s.mm_ticket_ttl_seconds == 2.5
    assert s.mm_greeter_pools == ["300+0"]
