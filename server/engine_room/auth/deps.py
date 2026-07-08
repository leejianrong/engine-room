"""FastAPI-Users wiring + the auth dependencies used by REST routes.

`current_active_user` is the seam integration tests override
(`app.dependency_overrides[current_active_user] = lambda: some_user`) to exercise
bot CRUD without going through the OAuth flow (D-i).
"""

import uuid

from fastapi_users import FastAPIUsers

from ..persistence.models import User
from .backend import auth_backend
from .users import get_user_manager

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
