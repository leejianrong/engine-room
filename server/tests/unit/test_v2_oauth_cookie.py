"""The OAuth CSRF cookie's Secure flag follows ER_OAUTH_COOKIE_SECURE.

Secure by default (HTTPS prod); flippable off so the real GitHub flow works over
plain http://localhost in dev. The /authorize endpoint touches no DB, so this is
a unit test."""

from starlette.testclient import TestClient

from engine_room.app import create_app
from engine_room.config import settings


def _authorize_set_cookie() -> str:
    client = TestClient(create_app())
    resp = client.get("/api/auth/github/authorize")
    assert resp.status_code == 200
    return resp.headers.get("set-cookie", "")


def test_cookie_is_secure_by_default(monkeypatch):
    monkeypatch.setattr(settings, "oauth_cookie_secure", True)
    assert "Secure" in _authorize_set_cookie()


def test_cookie_secure_can_be_disabled_for_dev(monkeypatch):
    monkeypatch.setattr(settings, "oauth_cookie_secure", False)
    assert "Secure" not in _authorize_set_cookie()
