"""Authentication backend: HttpOnly cookie transport + revocable DatabaseStrategy (KAN-72).

Human sessions ride a **same-origin HttpOnly cookie** (`er_session`): the SPA is
served by the same uvicorn process (KAN-68), so the browser sends the cookie
automatically on every API call — no `Authorization` header plumbing, and the JS
can't read the token (HttpOnly, XSS-hardened).

The strategy is FastAPI-Users' **`DatabaseStrategy`** (KAN-72): each live session is
a row in the `accesstoken` table (opaque token → user). This makes sessions
**revocable** — logout (`POST /api/auth/jwt/logout`), and future admin revocation,
delete the row so the cookie is rejected *instantly*, unlike the old stateless JWT
that stayed valid until expiry. The token table is created by migration 0006.

The OAuth callback finishes by 302-redirecting the browser back into the SPA
(`/bots`) with the session cookie set on the redirect response — so GitHub login
lands the human back in the app instead of on a raw-JSON page (KAN-64).
"""

from fastapi import Depends
from fastapi.responses import RedirectResponse
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy import DatabaseStrategy
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from starlette.responses import Response

from ..config import settings
from .users import get_access_token_db

# Where the browser lands after a successful GitHub login (the bot-management SPA route).
LOGIN_REDIRECT_URL = "/bots"


class RedirectCookieTransport(CookieTransport):
    """A cookie transport whose login response is a 302 back into the SPA.

    FastAPI-Users' plain `CookieTransport.get_login_response` answers 204 with a
    `Set-Cookie`. For the browser OAuth flow we instead want to *navigate* the
    browser home, so we return a `RedirectResponse` and set the login cookie on
    it (reusing the parent's cookie-setting logic so the `Set-Cookie` rides the
    302). Logout is unchanged (parent's 204 + cookie-clear).
    """

    async def get_login_response(self, token: str) -> Response:
        response = RedirectResponse(url=LOGIN_REDIRECT_URL, status_code=302)
        return self._set_login_cookie(response, token)


cookie_transport = RedirectCookieTransport(
    cookie_name="er_session",
    cookie_max_age=settings.auth_jwt_lifetime_seconds,
    cookie_secure=settings.oauth_cookie_secure,  # off for local http dev, on in prod
    cookie_httponly=True,
    cookie_samesite="lax",
)


def get_database_strategy(
    access_token_db: SQLAlchemyAccessTokenDatabase = Depends(get_access_token_db),
) -> DatabaseStrategy:
    return DatabaseStrategy(
        access_token_db,
        lifetime_seconds=settings.auth_jwt_lifetime_seconds,
    )


# `name="jwt"` is kept unchanged: the registered route paths come from the router
# `prefix` in app.py (`/api/auth/jwt/{login,logout}`), not this name, so the SPA's
# login/logout/callback URLs are unaffected. Only the *strategy* changed (KAN-72).
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)
