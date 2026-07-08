"""GitHub OAuth (ADR-0013) — the human sign-in flow.

FastAPI-Users' OAuth router exposes `authorize` (→ GitHub) and `callback`
(GitHub → us): the callback exchanges the code, reads the GitHub id + email,
finds-or-creates the User (+ an OAuthAccount row), and issues a session JWT via
the shared auth backend (D-l).

The provider client is a module-level singleton so tests can stub it (D-i) by
monkeypatching `github_oauth_client.get_access_token` / `.get_id_email` — no real
GitHub round-trip in CI.
"""

from fastapi import APIRouter
from httpx_oauth.clients.github import GitHubOAuth2

from ..config import settings
from .backend import auth_backend
from .deps import fastapi_users

github_oauth_client = GitHubOAuth2(
    settings.github_oauth_client_id,
    settings.github_oauth_client_secret,
)


def make_github_oauth_router() -> APIRouter:
    """Build the GitHub OAuth router.

    `associate_by_email`: a returning user who first signed in via another method
    (future: password) is linked by email rather than duplicated. GitHub verifies
    emails, so OAuth users are trusted as verified.
    """
    return fastapi_users.get_oauth_router(
        github_oauth_client,
        auth_backend,
        settings.auth_secret,
        redirect_url=settings.github_oauth_redirect_url,
        associate_by_email=True,
        is_verified_by_default=True,
    )
