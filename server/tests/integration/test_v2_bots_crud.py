"""Sub-step 3 checkpoint (integration): bot CRUD, owner-scoped, 5-per-user cap.

Auth is exercised via the `as_user` dependency override (D-i) rather than a real
OAuth round-trip. Needs Docker.
"""

from engine_room.bots import MAX_BOTS_PER_USER


async def test_create_returns_bot_with_key_once(client, make_user, as_user):
    as_user(await make_user())
    r = await client.post("/api/bots", json={"name": "my-bot", "description": "hi"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "my-bot"
    assert body["description"] == "hi"
    assert body["rating"] == 1200  # US 8 default (moves in V5)
    assert body["api_key"].startswith("crbk_")  # shown once at creation (US 11)
    assert body["key_prefix"] and body["key_prefix"] in body["api_key"]

    # A subsequent GET never returns the plaintext key (US 14).
    got = (await client.get(f"/api/bots/{body['id']}")).json()
    assert "api_key" not in got
    assert got["key_prefix"] == body["key_prefix"]


async def test_list_and_get_are_owner_scoped(client, make_user, as_user):
    alice = await make_user("alice@example.com")
    bob = await make_user("bob@example.com")

    as_user(alice)
    created = (await client.post("/api/bots", json={"name": "alice-bot"})).json()

    # Alice sees her bot
    assert [b["id"] for b in (await client.get("/api/bots")).json()] == [created["id"]]
    assert (await client.get(f"/api/bots/{created['id']}")).status_code == 200

    # Bob sees nothing and cannot fetch Alice's bot
    as_user(bob)
    assert (await client.get("/api/bots")).json() == []
    assert (await client.get(f"/api/bots/{created['id']}")).status_code == 404


async def test_five_bot_cap(client, make_user, as_user):
    as_user(await make_user())
    for i in range(MAX_BOTS_PER_USER):
        assert (await client.post("/api/bots", json={"name": f"bot-{i}"})).status_code == 201
    over = await client.post("/api/bots", json={"name": "one-too-many"})
    assert over.status_code == 409
    assert (await client.get("/api/bots")).json().__len__() == MAX_BOTS_PER_USER


async def test_delete(client, make_user, as_user):
    as_user(await make_user())
    bot_id = (await client.post("/api/bots", json={"name": "doomed"})).json()["id"]
    assert (await client.delete(f"/api/bots/{bot_id}")).status_code == 204
    assert (await client.get(f"/api/bots/{bot_id}")).status_code == 404
    assert (await client.delete(f"/api/bots/{bot_id}")).status_code == 404  # already gone


async def test_unauthenticated_is_rejected(client):
    # No as_user override → no Bearer token → 401.
    assert (await client.post("/api/bots", json={"name": "x"})).status_code == 401
