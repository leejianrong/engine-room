"""Sub-step 4 checkpoint (integration): key lifecycle + Postgres authenticator.

Create reveals the key once; the key authenticates a bot via
PostgresBotAuthenticator; rotation instantly invalidates the old key. Needs Docker.
"""

from engine_room.bots.authenticator import PostgresBotAuthenticator


async def test_key_authenticates_and_rotation_invalidates(
    client, session_factory, make_user, as_user
):
    as_user(await make_user())
    created = (await client.post("/api/bots", json={"name": "keyed"})).json()
    key1 = created["api_key"]

    authn = PostgresBotAuthenticator(session_factory=session_factory)

    # The freshly issued key authenticates to the right bot identity.
    info = await authn.authenticate(key1)
    assert info is not None
    assert info.id == created["id"]
    assert info.name == "keyed"
    assert info.rating == 1200

    # Wrong / empty keys are rejected.
    assert await authn.authenticate("crbk_not-a-real-key") is None
    assert await authn.authenticate("") is None

    # Rotation: new key works, old key is dead immediately (ADR-0014).
    rotated = (await client.post(f"/api/bots/{created['id']}/rotate-key")).json()
    key2 = rotated["api_key"]
    assert key2 != key1
    assert (await authn.authenticate(key2)) is not None
    assert (await authn.authenticate(key1)) is None


async def test_rotate_unknown_bot_is_404(client, make_user, as_user):
    as_user(await make_user())
    assert (await client.post("/api/bots/bot_nope/rotate-key")).status_code == 404
