"""KAN-72 (integration): revocable human sessions via the DatabaseStrategy.

The human auth backend now uses FastAPI-Users' `DatabaseStrategy` — each live
`er_session` cookie is a row in the `accesstoken` table. This proves the whole
point of the slice: a session can be killed *server-side* (logout or a direct row
delete = future admin revocation) so the same cookie is rejected instantly, unlike
the old stateless JWT that stayed valid until expiry.

Drives the real GitHub-OAuth login (provider stubbed, D-i) to obtain a genuine
DB-backed session cookie, then revokes it two ways. Needs Docker (testcontainers).
"""

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from engine_room.auth import oauth
from engine_room.persistence.models import AccessToken

SESSION_COOKIE = "er_session"


@pytest.fixture
def stub_github(monkeypatch):
    async def fake_get_access_token(*args, **kwargs):
        return {"access_token": "gho_fake", "token_type": "bearer", "expires_at": None}

    async def fake_get_id_email(access_token):
        return ("gh-72000", "revoke@example.com")

    monkeypatch.setattr(oauth.github_oauth_client, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(oauth.github_oauth_client, "get_id_email", fake_get_id_email)


async def _login(client) -> str:
    """Drive authorize → callback; return the session-cookie value the DB backs."""
    authz = await client.get("/api/auth/github/authorize")
    assert authz.status_code == 200, authz.text
    state = parse_qs(urlparse(authz.json()["authorization_url"]).query)["state"][0]
    cb = await client.get(
        "/api/auth/github/callback", params={"code": "code123", "state": state}
    )
    assert cb.status_code == 302, cb.text
    assert SESSION_COOKIE in cb.cookies, cb.headers.get("set-cookie")
    return cb.cookies[SESSION_COOKIE]


async def test_login_creates_db_backed_session_row(client, session_factory, stub_github):
    token = await _login(client)

    # The session works and there is exactly one server-side token row for it.
    me = await client.get("/api/users/me")
    assert me.status_code == 200, me.text

    async with session_factory() as s:
        rows = (await s.execute(select(AccessToken))).scalars().all()
    assert [r.token for r in rows] == [token]


async def test_logout_revokes_the_session_instantly(client, session_factory, stub_github):
    token = await _login(client)
    assert (await client.get("/api/users/me")).status_code == 200

    # Logout destroys the token row (DatabaseStrategy.destroy_token).
    logout = await client.post("/api/auth/jwt/logout")
    assert logout.status_code == 204, logout.text

    async with session_factory() as s:
        rows = (await s.execute(select(AccessToken))).scalars().all()
    assert rows == []

    # Re-presenting the *same* cookie value is now rejected — proving revocation is
    # server-side, not merely the client clearing its jar. Send it as a raw Cookie
    # header (not the client jar) so the exact revoked value reaches the server.
    replay = await client.get(
        "/api/users/me", headers={"Cookie": f"{SESSION_COOKIE}={token}"}
    )
    assert replay.status_code == 401, replay.text


async def test_deleting_the_token_row_kills_the_session(client, session_factory, stub_github):
    """Direct row delete = the future admin-revocation path: the cookie dies at once."""
    token = await _login(client)
    assert (await client.get("/api/users/me")).status_code == 200

    async with session_factory() as s:
        row = (
            await s.execute(select(AccessToken).where(AccessToken.token == token))
        ).scalar_one()
        await s.delete(row)
        await s.commit()

    denied = await client.get(
        "/api/users/me", headers={"Cookie": f"{SESSION_COOKIE}={token}"}
    )
    assert denied.status_code == 401, denied.text
