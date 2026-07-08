"""Sub-step 5 checkpoint (integration): rotating a key terminates the bot's live
session immediately (ADR-0014). Single-process MVP: the REST rotate handler and
the WS session share one event loop, so it can close the socket directly.

A lightweight fake WebSocket stands in for the live socket (the REST↔WS bridge is
what's under test, not the socket transport). Needs Docker (for the bot row)."""

from engine_room.protocol.messages import BotInfo
from engine_room.ws.session import CLOSE_SESSION_REPLACED, Session


class _FakeWs:
    def __init__(self) -> None:
        self.close_code: int | None = None
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int) -> None:
        self.close_code = code


async def test_rotation_evicts_and_closes_live_session(client, app, make_user, as_user):
    as_user(await make_user())
    bot_id = (await client.post("/api/bots", json={"name": "b"})).json()["id"]

    # Plant a live session for this bot in the registry (as if it were connected).
    fake_ws = _FakeWs()
    live = Session(fake_ws, bot=BotInfo(id=bot_id, name="b", rating=1200), session_id="sess_x")
    app.state.session_registry.register(live)

    resp = await client.post(f"/api/bots/{bot_id}/rotate-key")
    assert resp.status_code == 200

    # The live session was evicted and its socket closed.
    assert app.state.session_registry.current(bot_id) is None
    assert fake_ws.close_code == CLOSE_SESSION_REPLACED
    assert any("SESSION_REPLACED" in frame for frame in fake_ws.sent)
