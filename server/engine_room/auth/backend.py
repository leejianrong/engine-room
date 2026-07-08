"""Authentication backend: Bearer transport + stateless JWT strategy (D-l).

Stateless JWT means no session table and no Redis (MVP scope, R5). The token is
carried in `Authorization: Bearer <jwt>` — symmetric with how bots present their
API key, and friction-free for the REST-driven V2 demo/tests (D-j).
"""

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)

from ..config import settings

bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=settings.auth_secret,
        lifetime_seconds=settings.auth_jwt_lifetime_seconds,
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
