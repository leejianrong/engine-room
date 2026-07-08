"""Pydantic schemas for the bot management API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=256)


class BotRead(BaseModel):
    """A bot as returned by the API — never includes the secret key, only the
    non-secret display prefix (US 14: keys are stored only as hashes)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    rating: int
    key_prefix: str | None  # e.g. "crbk_a1b2c3d4" for identification; None until generated
    created_at: datetime


class BotWithKey(BotRead):
    """Returned exactly once, at key generation/rotation (US 11). The plaintext
    `api_key` is unrecoverable afterwards."""

    api_key: str
