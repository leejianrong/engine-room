"""tournaments: round-robin events, entries (standings), scheduled games (KAN-56)

First tournament slice — persisted round-robin only (swiss + elimination brackets
are deferred follow-up cards). Adds three tables and NO change to `games`:

  - `tournaments`         one event: name, format, time control, target size, status
  - `tournament_entries`  one enrolled bot + its running score; unique(tournament,bot)
  - `tournament_games`    the schedule AND results: one row per pairing, with a
                          nullable `game_id` FK → games (NULL for forfeit/void/bye)

Keeping the played-game link in `tournament_games.game_id` (rather than a
`tournament_id` column on `games`) leaves the finalizer's hot write path untouched
and lets unplayed pairings (forfeits, byes) be recorded without a `games` row.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-13

"""

from typing import Sequence, Union

import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUID = fastapi_users_db_sqlalchemy.generics.GUID


def upgrade() -> None:
    op.create_table(
        "tournaments",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("base_seconds", sa.Integer(), nullable=False),
        sa.Column("increment_seconds", sa.Integer(), nullable=False),
        sa.Column("target_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", _GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_tournaments_created_by"), "tournaments", ["created_by"])

    op.create_table(
        "tournament_entries",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tournament_id", sa.String(length=40), nullable=False),
        sa.Column("bot_id", sa.String(length=40), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tournament_id", "bot_id", name="uq_entry_tour_bot"),
    )
    op.create_index(
        op.f("ix_tournament_entries_tournament_id"),
        "tournament_entries",
        ["tournament_id"],
    )

    op.create_table(
        "tournament_games",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("tournament_id", sa.String(length=40), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("white_bot_id", sa.String(length=40), nullable=True),
        sa.Column("black_bot_id", sa.String(length=40), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=True),
        sa.Column("game_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["white_bot_id"], ["bots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["black_bot_id"], ["bots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="SET NULL"),
    )
    op.create_index(
        op.f("ix_tournament_games_tournament_id"),
        "tournament_games",
        ["tournament_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tournament_games_tournament_id"), table_name="tournament_games")
    op.drop_table("tournament_games")
    op.drop_index(
        op.f("ix_tournament_entries_tournament_id"), table_name="tournament_entries"
    )
    op.drop_table("tournament_entries")
    op.drop_index(op.f("ix_tournaments_created_by"), table_name="tournaments")
    op.drop_table("tournaments")
