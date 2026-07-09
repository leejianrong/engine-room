"""house-bot personas: seed ephraim-bot; rename house-random(-2) → jian-bot-001/002

Data-only — no DDL. Post-MVP house-bot personas change:
- Seeds the new **ephraim-bot** identity (the ephemeral Kind-2 greeter), split off
  from the shared `bot_house_random` so the greeter no longer shares an identity
  with a permanent bot.
- Renames the two permanent ambient bots' display names to **jian-bot-001** /
  **jian-bot-002** (Kind-1). IDs are kept stable (`bot_house_random`,
  `bot_house_random_2`) so existing games' FKs/history survive; only the `name`
  changes. Their mover switches to minimax in app wiring (no DB effect).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-10

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New ephemeral greeter identity.
    op.execute(
        "INSERT INTO bots (id, name, description, rating, games_played, is_house, created_at) "
        "VALUES ('bot_ephraim', 'ephraim-bot', "
        "'Ephemeral house greeter — easy random opponent for a newcomer''s first game.', "
        "1200, 0, true, now()) "
        "ON CONFLICT (id) DO NOTHING"
    )
    # Rename the permanent ambient bots (ids stay; only display name changes).
    op.execute(
        "UPDATE bots SET name = 'jian-bot-001', "
        "description = 'Permanent house bot — plays minimax + alpha-beta.' "
        "WHERE id = 'bot_house_random'"
    )
    op.execute(
        "UPDATE bots SET name = 'jian-bot-002', "
        "description = 'Permanent house bot — plays minimax + alpha-beta.' "
        "WHERE id = 'bot_house_random_2'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE bots SET name = 'house-random', "
        "description = 'Built-in random-move house bot.' WHERE id = 'bot_house_random'"
    )
    op.execute(
        "UPDATE bots SET name = 'house-random-2', "
        "description = 'Built-in random-move house bot.' WHERE id = 'bot_house_random_2'"
    )
    op.execute("DELETE FROM bots WHERE id = 'bot_ephraim'")
