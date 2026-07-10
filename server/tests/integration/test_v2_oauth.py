"""Sub-step 2 checkpoint (integration): GitHub OAuth sign-in.

The GitHub provider is stubbed (D-i) by monkeypatching the module-level client's
`get_access_token` / `get_id_email` — no real GitHub round-trip. We drive the
real router: `authorize` (mints state + CSRF cookie) → `callback` (verifies both,
creates the User + OAuthAccount, sets the `er_session` HttpOnly cookie and
302-redirects the browser back into the SPA, KAN-64). Needs Docker.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from engine_room.auth import oauth
from engine_room.persistence.models import OAuthAccount, User

SESSION_COOKIE = "er_session"


@pytest.fixture
def stub_github(monkeypatch):
    async def fake_get_access_token(*args, **kwargs):
        return {"access_token": "gho_fake", "token_type": "bearer", "expires_at": None}

    async def fake_get_id_email(access_token):
        return ("gh-12345", "dev@example.com")

    monkeypatch.setattr(oauth.github_oauth_client, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(oauth.github_oauth_client, "get_id_email", fake_get_id_email)


async def _complete_login(client):
    """Drive authorize → callback; assert the 302-redirect-with-cookie contract.

    Returns the callback response. `client` doesn't follow redirects (httpx
    default) but does store the `Set-Cookie` in its jar, so subsequent calls on
    the same client are authenticated by the session cookie.
    """
    authz = await client.get("/api/auth/github/authorize")
    assert authz.status_code == 200, authz.text
    state = parse_qs(urlparse(authz.json()["authorization_url"]).query)["state"][0]
    cb = await client.get(
        "/api/auth/github/callback", params={"code": "code123", "state": state}
    )
    # KAN-64: the callback redirects the browser back into the SPA and sets the
    # session cookie on the 302 (not a raw-JSON body).
    assert cb.status_code == 302, cb.text
    assert cb.headers["location"] == "/bots"
    assert SESSION_COOKIE in cb.cookies, cb.headers.get("set-cookie")
    return cb


async def test_callback_creates_user_and_oauth_account(client, session_factory, stub_github):
    await _complete_login(client)

    # The session cookie now authenticates a REST call (proves the cookie works).
    me = await client.get("/api/users/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "dev@example.com"

    async with session_factory() as s:
        users = (await s.execute(select(User))).unique().scalars().all()
        accts = (await s.execute(select(OAuthAccount))).scalars().all()

    assert len(users) == 1
    assert users[0].email == "dev@example.com"
    assert users[0].is_verified is True  # is_verified_by_default (GitHub verifies emails)
    assert len(accts) == 1
    assert accts[0].oauth_name == "github"
    assert accts[0].account_id == "gh-12345"


async def test_second_login_same_github_id_is_idempotent(client, session_factory, stub_github):
    await _complete_login(client)
    await _complete_login(client)  # same GitHub id/email → no duplicate user

    async with session_factory() as s:
        users = (await s.execute(select(User))).unique().scalars().all()
    assert len(users) == 1


async def test_callback_rejects_forged_state(client, stub_github):
    # A state token not minted by /authorize (no matching CSRF cookie) is refused.
    cb = await client.get(
        "/api/auth/github/callback", params={"code": "code123", "state": "not-a-real-state"}
    )
    assert cb.status_code == 400
