"""access_tokens: server-side revocable human sessions (KAN-72)

Adds FastAPI-Users' access-token table (`accesstoken`) backing the auth backend's
`DatabaseStrategy` (KAN-72). Each live `er_session` cookie is now a row here
(opaque token → user), so logout / future admin revocation deletes the row and
kills the session instantly — the stateless JWT it replaces could not be revoked
before expiry.

Columns mirror `SQLAlchemyBaseAccessTokenTableUUID`:
  - `token`      VARCHAR(43) primary key
  - `created_at` timestamptz NOT NULL, indexed
  - `user_id`    GUID NOT NULL, FK → user.id ON DELETE CASCADE

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-13

"""

from typing import Sequence, Union

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUID = fastapi_users_db_sqlalchemy.generics.GUID


def upgrade() -> None:
    op.create_table(
        "accesstoken",
        sa.Column("token", sa.String(length=43), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", _GUID(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="cascade"),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index(
        op.f("ix_accesstoken_created_at"), "accesstoken", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_accesstoken_created_at"), table_name="accesstoken")
    op.drop_table("accesstoken")
