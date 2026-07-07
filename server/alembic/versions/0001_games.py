"""games table (V1 minimal, V1-plan.md)

Revision ID: 0001
Revises:
Create Date: 2026-07-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "games",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("termination", sa.String(length=32), nullable=False),
        sa.Column("final_fen", sa.String(length=120), nullable=False),
        sa.Column("pgn", sa.Text(), nullable=False),
        sa.Column("base_seconds", sa.Integer(), nullable=False),
        sa.Column("increment_seconds", sa.Integer(), nullable=False),
        sa.Column("white_name", sa.String(length=64), nullable=False),
        sa.Column("black_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("games")
