"""identity: user + oauth_account + bots + games bot FKs (V2 / slice A2)

Adds the FastAPI-Users human-identity tables (ADR-0013), the user-owned Bot table
(ADR-0009/0014), the `games` bot-FK columns (ADR-0009), and seeds the built-in
house bot so those FKs resolve for house games (ADR-0022).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08

"""

from typing import Sequence, Union

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUID = fastapi_users_db_sqlalchemy.generics.GUID


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", _GUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_email"), "user", ["email"], unique=True)

    op.create_table(
        "oauth_account",
        sa.Column("id", _GUID(), nullable=False),
        sa.Column("user_id", _GUID(), nullable=False),
        sa.Column("oauth_name", sa.String(length=100), nullable=False),
        sa.Column("access_token", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.Column("refresh_token", sa.String(length=1024), nullable=True),
        sa.Column("account_id", sa.String(length=320), nullable=False),
        sa.Column("account_email", sa.String(length=320), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="cascade"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_oauth_account_account_id"), "oauth_account", ["account_id"]
    )
    op.create_index(
        op.f("ix_oauth_account_oauth_name"), "oauth_account", ["oauth_name"]
    )

    op.create_table(
        "bots",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_id", _GUID(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("is_house", sa.Boolean(), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=True),
        sa.Column("key_prefix", sa.String(length=16), nullable=True),
        sa.Column("key_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bots_owner_id"), "bots", ["owner_id"])
    op.create_index(op.f("ix_bots_key_hash"), "bots", ["key_hash"], unique=True)

    # Seed the built-in random house bot (owner NULL, is_house) so house games'
    # FKs resolve. Values mirror engine_room.game.house_bots.HOUSE_RANDOM_*.
    op.execute(
        "INSERT INTO bots (id, name, description, rating, is_house, created_at) "
        "VALUES ('bot_house_random', 'house-random', "
        "'Built-in random-move house bot.', 1200, true, now())"
    )

    # games gains real bot FKs (ADR-0009); nullable + SET NULL so bot deletion
    # (US 9) doesn't erase history. The V1 *_name snapshot columns are kept (D-f).
    op.add_column("games", sa.Column("white_bot_id", sa.String(length=40), nullable=True))
    op.add_column("games", sa.Column("black_bot_id", sa.String(length=40), nullable=True))
    op.create_foreign_key(
        "fk_games_white_bot", "games", "bots", ["white_bot_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_games_black_bot", "games", "bots", ["black_bot_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_games_black_bot", "games", type_="foreignkey")
    op.drop_constraint("fk_games_white_bot", "games", type_="foreignkey")
    op.drop_column("games", "black_bot_id")
    op.drop_column("games", "white_bot_id")
    op.drop_index(op.f("ix_bots_key_hash"), table_name="bots")
    op.drop_index(op.f("ix_bots_owner_id"), table_name="bots")
    op.drop_table("bots")
    op.drop_index(op.f("ix_oauth_account_oauth_name"), table_name="oauth_account")
    op.drop_index(op.f("ix_oauth_account_account_id"), table_name="oauth_account")
    op.drop_table("oauth_account")
    op.drop_index(op.f("ix_user_email"), table_name="user")
    op.drop_table("user")
