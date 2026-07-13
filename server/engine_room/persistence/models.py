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
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    """Server-side human session token (KAN-72). Backs the `DatabaseStrategy`:
    a row per live `er_session` cookie, so logout (and future admin revocation)
    deletes the row and kills the session *instantly* — unlike the old stateless
    JWT, which could not be revoked before expiry. The mixin supplies `token`
    (PK), `created_at`, and the `user_id` FK → `user.id`; table name `accesstoken`.
    """


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


# --- KAN-56 tournaments (round-robin, first slice) ------------------------------
# Persisted, single-process-orchestrated (like MatchmakingQueue). A `TournamentManager`
# on app.state enrolls bots (via a tournament-tagged `seek`), generates the circle-
# method schedule at start, launches each game over the existing GameLauncher, and
# writes standings back here as games finalize. Only round-robin is built now; swiss
# + elimination brackets are deferred follow-up cards.


class Tournament(Base):
    """A persisted tournament. `format` is fixed to 'round_robin' in this slice.

    `target_size` is the number of entrants that auto-starts the event (also
    startable explicitly). Lifecycle: pending → running → finished (ADR-0010-style
    vocabulary, tournament-scoped)."""

    __tablename__ = "tournaments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "tour_..."
    name: Mapped[str] = mapped_column(String(128))
    format: Mapped[str] = mapped_column(String(16), default="round_robin")
    base_seconds: Mapped[int] = mapped_column(Integer)  # time control base (e.g. 180)
    increment_seconds: Mapped[int] = mapped_column(Integer, default=0)
    target_size: Mapped[int] = mapped_column(Integer)  # entrants that auto-start it
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|finished
    # Creating human (US-style owner). Nullable + SET NULL so a user deletion keeps
    # the tournament's history (mirrors games' bot FKs, D-f).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TournamentEntry(Base):
    """One bot enrolled in a tournament + its running score (win=1, draw=0.5).

    A bot enrolls by seeking with a `tournament_id`; `unique(tournament_id, bot_id)`
    makes a double-enroll a no-op at the DB level as well as in the manager."""

    __tablename__ = "tournament_entries"
    __table_args__ = (UniqueConstraint("tournament_id", "bot_id", name="uq_entry_tour_bot"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "tent_..."
    tournament_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    bot_id: Mapped[str] = mapped_column(String(40), ForeignKey("bots.id", ondelete="CASCADE"))
    seed: Mapped[int] = mapped_column(Integer)  # join order — drives pairing rotation
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")


class TournamentGame(Base):
    """One scheduled pairing + its result — the schedule AND the results table.

    Written pending (result NULL) when the schedule is generated, then filled in as
    each pairing resolves. `game_id` links to the actual `games` row when a real game
    was played; it stays NULL for a forfeit (an entrant offline when its game was
    due), a `void` (both offline), or a `bye` (odd field). This keeps the hot `games`
    write path (the finalizer) untouched — all tournament state lives here — and lets
    unplayed pairings be represented without a games row (which a `tournament_id`
    column on `games` could not do). `black_bot_id` is NULL on a bye."""

    __tablename__ = "tournament_games"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "tgame_..."
    tournament_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("tournaments.id", ondelete="CASCADE"), index=True
    )
    round: Mapped[int] = mapped_column(Integer)  # 0-based round number
    white_bot_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("bots.id", ondelete="SET NULL"), nullable=True
    )
    black_bot_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("bots.id", ondelete="SET NULL"), nullable=True
    )
    # NULL until resolved; then white_wins|black_wins|draw (played or forfeit) |
    # void (both offline) | bye (odd field). aborted games score no points.
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    game_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("games.id", ondelete="SET NULL"), nullable=True
    )
