"""ambient: seed the second house bot (V6 / slice A6)

Data-only — no DDL. Seeds `house-random-2` (owner NULL, is_house) so ambient
house-vs-house games (ADR-0022 Kind-1) have two distinct rated, persisted bots
whose `games.white_bot_id`/`black_bot_id` FKs resolve. Mirrors the 0002
house-bot seed and engine_room.game.house_bots.HOUSE_RANDOM_2_*.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-09

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO bots (id, name, description, rating, games_played, is_house, created_at) "
        "VALUES ('bot_house_random_2', 'house-random-2', "
        "'Built-in random-move house bot.', 1200, 0, true, now()) "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM bots WHERE id = 'bot_house_random_2'")
