"""Mint a real bot API key locally, skipping the GitHub OAuth flow (dev only).

Since V2 the WS handshake authenticates a real `crbk_` key (PostgresBotAuthenticator),
so seeing a game locally used to require signing in with GitHub and creating a bot
via REST. This provisions the same thing straight from the DB — a dev user + one
bot — and prints a fresh key. It uses the **production** key path (real hashing,
`ER_API_KEY_PEPPER`); it is not an auth bypass, just a shortcut past the browser.

Idempotent: re-running **rotates** the same dev bot's key (a fresh usable key each
time) rather than piling up bots against the 5-per-user cap.

    cd server
    uv run python -m engine_room.devtools.mint_bot            # friendly output
    uv run python -m engine_room.devtools.mint_bot --quiet    # prints ONLY the key

Talks to `ER_DATABASE_URL` (default: local Postgres on :5433). Run `alembic
upgrade head` first so the tables + house bot exist.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from ..bots.schemas import BotCreate
from ..bots.service import create_bot, list_bots, rotate_key
from ..persistence.db import SessionLocal
from ..persistence.models import User

DEV_EMAIL = "dev@local.test"
DEV_BOT_NAME = "local-dev-bot"


async def _get_or_create_dev_user(session, email: str) -> User:
    user = await session.scalar(select(User).where(User.email == email))
    if user is not None:
        return user
    user = User(
        email=email,
        hashed_password="local-dev-no-password",  # OAuth-style: never used to log in
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def mint_key(name: str = DEV_BOT_NAME, email: str = DEV_EMAIL) -> tuple[str, str]:
    """Ensure a dev user + a bot named `name`, and return `(bot_id, api_key)`.

    Creates the bot on first run; rotates its key on subsequent runs."""
    async with SessionLocal() as session:
        user = await _get_or_create_dev_user(session, email)
        existing = next((b for b in await list_bots(session, user.id) if b.name == name), None)
        if existing is None:
            bot, key = await create_bot(session, user.id, BotCreate(name=name))
        else:
            bot, key = await rotate_key(session, user.id, existing.id)  # type: ignore[misc]
        return bot.id, key


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Mint a local bot API key (dev only).")
    parser.add_argument("--name", default=DEV_BOT_NAME, help="bot name to create/rotate")
    parser.add_argument("--email", default=DEV_EMAIL, help="dev user email")
    parser.add_argument(
        "--quiet", action="store_true", help="print only the key (for scripting)"
    )
    args = parser.parse_args()

    bot_id, key = await mint_key(args.name, args.email)
    if args.quiet:
        print(key)
    else:
        print(f"\n  bot id : {bot_id}")
        print(f"  api key: {key}")
        print("\n  Use it:  --token " + key + "\n")


if __name__ == "__main__":
    asyncio.run(_main())
