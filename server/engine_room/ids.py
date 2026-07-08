"""Prefixed opaque identifiers (e.g. sess_, seek_, game_, bot_)."""

import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
