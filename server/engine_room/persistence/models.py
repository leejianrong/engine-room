"""SQLAlchemy ORM models — durable records written at game finalization (ADR-0018).

V1 minimal schema (V1-plan.md D-a). Forward-compatible:
  - V2 (A2) adds white_bot_id / black_bot_id FKs to a bots table.
  - V5 (A5) adds rating-delta columns.
Alembic manages that growth.
"""

import uuid
from datetime import datetime

from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTableUUID,
    SQLAlchemyBaseUserTableUUID,
)
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- V2 identity (slice A2) -----------------------------------------------------
# User/OAuthAccount are FastAPI-Users' tables (ADR-0013). The mixins supply the
# columns; combined with our Base they become the `user` / `oauth_account` tables.
# The default table name `user` is a Postgres reserved word but SQLAlchemy quotes
# identifiers, and the OAuth FK is hardcoded to `user.id`, so we keep the defaults.


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    # lazy="joined" so the SQLAlchemy adapter can resolve a user by OAuth account
    # in one query (FastAPI-Users' documented pattern).
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount", lazy="joined"
    )


class Bot(Base):
    """A user-owned (or house) bot — first-class, persistent identity (ADR-0009).

    One rotatable API key per bot (ADR-0014), stored only as `key_hash` (D-k); the
    plaintext is shown once at generation and never persisted. House bots have
    `owner_id = NULL`, `is_house = True`, and no key (they run in-process).
    """

    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "bot_..."
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True
    )  # NULL = house bot
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(256), default="")
    rating: Mapped[int] = mapped_column(Integer, default=1200)  # US 8; moves in V5
    # Rated games this bot has completed (FINISHED, not ABORTED). Drives the
    # provisional K-factor (larger K for the first N games, ADR-0011). Added in V5
    # (0003); counts from V5 onward — pre-V5 games are not backfilled (O-4).
    games_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_house: Mapped[bool] = mapped_column(Boolean, default=False)
    # API key (populated at key generation/rotation, sub-step 4)
    key_hash: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )
    key_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True)
    key_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "game_..."
    result: Mapped[str] = mapped_column(String(16))  # white_wins|black_wins|draw|aborted
    termination: Mapped[str] = mapped_column(String(32))  # ADR-0008 vocabulary
    final_fen: Mapped[str] = mapped_column(String(120))
    pgn: Mapped[str] = mapped_column(Text)  # python-chess rendered
    base_seconds: Mapped[int] = mapped_column(Integer)  # 180 for 3+0
    increment_seconds: Mapped[int] = mapped_column(Integer)  # 0 at MVP
    # V2: FKs to the real bots (ADR-0009). Nullable + ON DELETE SET NULL so a
    # user can delete a bot (US 9) without erasing its game history; the *_name
    # columns are kept as a denormalized snapshot that survives deletion (D-f).
    white_bot_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("bots.id", ondelete="SET NULL"), nullable=True
    )
    black_bot_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("bots.id", ondelete="SET NULL"), nullable=True
    )
    white_name: Mapped[str] = mapped_column(String(64))  # snapshot at game time
    black_name: Mapped[str] = mapped_column(String(64))
    # V5 (0003): per-color Elo before/after, written in the same finalize txn as
    # the row (ADR-0025 #5). NULL for ABORTED games (no result → no rating).
    white_rating_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    white_rating_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_rating_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_rating_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
