"""Sub-step 1 checkpoint: the FastAPI-Users identity surface is wired in.

No infra — asserts the app boots with the auth routes mounted, the ORM tables
are registered on the shared Base, and the `0002` migration chains onto `0001`.
Behavioural tests (OAuth callback, bot CRUD) live in tests/integration.
"""

from engine_room.app import create_app
from engine_room.auth.deps import current_active_user
from engine_room.persistence.models import Base


def test_users_router_mounted():
    spec = create_app().openapi()
    paths = spec["paths"]
    assert "/api/users/me" in paths


def test_current_active_user_dependency_exists():
    assert callable(current_active_user)


def test_identity_tables_registered():
    tables = set(Base.metadata.tables)
    assert {"user", "oauth_account", "games"} <= tables


def test_migration_0002_chains_onto_0001():
    # Import by file path to avoid depending on the module name.
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0002_identity.py"
    spec = importlib.util.spec_from_file_location("_v2_mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0002"
    assert mod.down_revision == "0001"
