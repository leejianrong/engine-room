"""SQLAlchemy ORM models — durable records written at game finalization (ADR-0018).

V1 minimal schema (V1-plan.md D-a). Forward-compatible:
  - V2 (A2) adds white_bot_id / black_bot_id FKs to a bots table.
  - V5 (A5) adds rating-delta columns.
Alembic manages that growth.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "game_..."
    result: Mapped[str] = mapped_column(String(16))  # white_wins|black_wins|draw|aborted
    termination: Mapped[str] = mapped_column(String(32))  # ADR-0008 vocabulary
    final_fen: Mapped[str] = mapped_column(String(120))
    pgn: Mapped[str] = mapped_column(Text)  # python-chess rendered
    base_seconds: Mapped[int] = mapped_column(Integer)  # 180 for 3+0
    increment_seconds: Mapped[int] = mapped_column(Integer)  # 0 at MVP
    white_name: Mapped[str] = mapped_column(String(64))  # V1: stub/house names; V2 -> FK
    black_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
