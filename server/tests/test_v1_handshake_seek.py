"""V1 sub-step 2 checkpoint: a fake client completes handshake + seek.

Primary WS test seam (PRD Option A). Asserts on the wire contract only.
"""

from fake_client import connect


def test_handshake_returns_welcome():
    with connect() as bot:
        welcome = bot.hello()
    assert welcome["type"] == "welcome"
    assert welcome["protocol_version"] == "1.0"
    assert welcome["session_id"].startswith("sess_")
    assert welcome["bot"]["rating"] == 1200
    assert welcome["active_game"] is None


def test_seek_returns_ack():
    with connect() as bot:
        bot.hello()
        ack = bot.seek(base_seconds=180, increment_seconds=0, cid="c1")
    assert ack["type"] == "seek_ack"
    assert ack["id"] == "c1"  # correlation id echoed
    assert ack["seek_id"].startswith("seek_")
    assert ack["status"] == "queued"


def test_missing_token_is_unauthorized():
    with connect(token=None) as bot:
        err = bot.recv()
    assert err["type"] == "error"
    assert err["code"] == "UNAUTHORIZED"
    assert err["fatal"] is True


def test_bad_token_is_unauthorized():
    with connect(token="wrong") as bot:
        err = bot.recv()
    assert err["code"] == "UNAUTHORIZED"


def test_unsupported_protocol_version():
    with connect() as bot:
        err = bot.hello(protocol_version="2.0")
    assert err["type"] == "error"
    assert err["code"] == "VERSION_UNSUPPORTED"
    assert err["fatal"] is True


def test_seek_before_hello_is_rejected():
    with connect() as bot:
        # Skip hello; a seek as the first frame is not a valid handshake.
        first = bot.seek()
    assert first["type"] == "error"
    assert first["code"] == "INVALID_MESSAGE"
    assert first["fatal"] is True


def test_unknown_message_type_is_non_fatal():
    with connect() as bot:
        bot.hello()
        bot.send({"type": "nonsense"})
        err = bot.recv()
        assert err["type"] == "error"
        assert err["code"] == "INVALID_MESSAGE"
        assert err["fatal"] is False
        # connection still usable: a subsequent seek still works
        ack = bot.seek(cid="c2")
    assert ack["type"] == "seek_ack"
    assert ack["id"] == "c2"


def test_malformed_json_is_non_fatal():
    with connect() as bot:
        bot.hello()
        bot.ws.send_text("{not json")
        err = bot.recv()
        assert err["code"] == "INVALID_MESSAGE"
        assert err["fatal"] is False
