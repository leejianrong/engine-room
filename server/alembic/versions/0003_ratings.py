"""ratings: games rating columns + bots.games_played (V5 / slice A5)

Adds the per-color Elo before/after columns to `games` and a rated-games counter
to `bots` (ADR-0011). At finalization the result, PGN, both rating deltas, and
the two `bots.rating`/`games_played` updates are written in ONE transaction
(ADR-0025 #5). Rating columns are nullable — an ABORTED game has no result and so
no rating (ADR-0010). First schema change since V2's 0002.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rated-games counter for the provisional K-factor. server_default so the
    # existing house-bot row (and any pre-V5 bots) get 0 without a data migration.
    op.add_column(
        "bots",
        sa.Column("games_played", sa.Integer(), nullable=False, server_default="0"),
    )
    for col in (
        "white_rating_before",
        "white_rating_after",
        "black_rating_before",
        "black_rating_after",
    ):
        op.add_column("games", sa.Column(col, sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "black_rating_after")
    op.drop_column("games", "black_rating_before")
    op.drop_column("games", "white_rating_after")
    op.drop_column("games", "white_rating_before")
    op.drop_column("bots", "games_played")
