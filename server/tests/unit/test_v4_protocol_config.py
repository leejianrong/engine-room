"""V4 sub-step 1 checkpoint: pong parses, ping serializes, heartbeat settings load."""

import pytest

from engine_room.config import Settings
from engine_room.protocol.messages import (
    Ping,
    Pong,
    ProtocolError,
    parse_client_message,
)


def test_parse_pong():
    msg = parse_client_message('{"type":"pong","t":1234}')
    assert isinstance(msg, Pong)
    assert msg.t == 1234


def test_parse_pong_without_t_defaults_to_zero():
    # The server only needs a pong to arrive; a bare pong is still valid.
    msg = parse_client_message('{"type":"pong"}')
    assert isinstance(msg, Pong)
    assert msg.t == 0


def test_pong_is_a_known_client_message():
    # Unknown types raise; pong must not.
    with pytest.raises(ProtocolError):
        parse_client_message('{"type":"pang"}')


def test_ping_serializes():
    assert Ping(t=42).model_dump() == {"type": "ping", "t": 42}


def test_heartbeat_settings_defaults():
    s = Settings()
    assert s.hb_ping_interval_seconds == 10.0
    assert s.hb_liveness_timeout_seconds == 30.0


def test_heartbeat_settings_env_override(monkeypatch):
    monkeypatch.setenv("ER_HB_PING_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("ER_HB_LIVENESS_TIMEOUT_SECONDS", "0.15")
    s = Settings()
    assert s.hb_ping_interval_seconds == 0.05
    assert s.hb_liveness_timeout_seconds == 0.15
