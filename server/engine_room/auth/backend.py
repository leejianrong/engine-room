"""Authentication backend: HttpOnly cookie transport + stateless JWT strategy (D-l).

Human sessions ride a **same-origin HttpOnly cookie** (`er_session`): the SPA is
served by the same uvicorn process (KAN-68), so the browser sends the cookie
automatically on every API call — no `Authorization` header plumbing, and the JS
can't read the token (HttpOnly, XSS-hardened). The token itself is still the
stateless JWT strategy (no session table / Redis, MVP scope R5); a revocable
DatabaseStrategy is a deferred follow-up.

The OAuth callback finishes by 302-redirecting the browser back into the SPA
(`/bots`) with the session cookie set on the redirect response — so GitHub login
lands the human back in the app instead of on a raw-JSON page (KAN-64).
"""

from fastapi.responses import RedirectResponse
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from starlette.responses import Response

from ..config import settings

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


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=settings.auth_secret,
        lifetime_seconds=settings.auth_jwt_lifetime_seconds,
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)
