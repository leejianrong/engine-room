"""Sub-step 5: the WS handshake authenticates a real key and binds the real
identity (single-connection cases; cross-socket newest-wins is a live-server
integration test). Primary WS seam."""

from support.fake_client import FakeBotAuthenticator, connect

from engine_room.app import create_app
from engine_room.protocol.messages import BotInfo


def test_welcome_carries_the_authenticated_bot_identity():
    authn = FakeBotAuthenticator(
        {"crbk_zeta": BotInfo(id="bot_z", name="zeta", rating=1500)}
    )
    with connect(token="crbk_zeta", authenticator=authn) as bot:
        welcome = bot.hello()
    # The session is bound to the real Bot (not V1's fixed stub identity).
    assert welcome["bot"] == {"id": "bot_z", "name": "zeta", "rating": 1500}


def test_unknown_key_is_unauthorized():
    authn = FakeBotAuthenticator(
        {"crbk_good": BotInfo(id="bot_g", name="g", rating=1200)}
    )
    with connect(token="crbk_bogus", authenticator=authn) as bot:
        err = bot.recv()
    assert err["type"] == "error"
    assert err["code"] == "UNAUTHORIZED"
    assert err["fatal"] is True


def test_null_authenticator_rejects_everything():
    # create_app() with no authenticator injected defaults to NullAuthenticator,
    # which must reject every key (no accidental auth bypass).
    with connect(app=create_app(), token="crbk_anything") as bot:
        err = bot.recv()
    assert err["code"] == "UNAUTHORIZED"
