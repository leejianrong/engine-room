"""Spectator read REST (V6, N9 / ADR-0015 F3+F5) — anonymous, read-only, CORS
like the SSE endpoint.

- `GET /api/games` — the lobby: active/paired games from the in-memory registry
  (ADR-0020) merged with the most-recently-finished games from Postgres (D-e).
- `GET /api/games/{id}` — the replay/detail view: a running game is projected
  from `LiveState`; a finished game from its stored PGN (D-d). One uniform
  `[{ply, san, uci, fen}]` move-list either way, so the client has ONE replay
  model.
- `GET /api/bots/{bot_id}/games` — a single bot's finished-game history + a
  W/L/D summary, shaped from THAT bot's perspective (KAN-53). Read-only, public,
  backs the future bot-profile pages (KAN-52).

Both `/api/games*` endpoints degrade gracefully when no `game_reader` is injected
(fast, DB-free tests): the lobby returns active games only; the detail serves an
in-memory game or 404s. The bot-history endpoint is purely durable (finished
games live only in Postgres), so it reads through the request-scoped
`get_async_session` DI seam (like `bots/routes.py` and the leaderboard) and 404s
on a bot that isn't in the database.
"""

from __future__ import annotations

import chess
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..game.game import Game
from ..persistence.db import get_async_session
from ..persistence.models import Bot as BotRow
from ..persistence.models import Game as GameRow

router = APIRouter()


def _tc(game: Game) -> dict:
    return {
        "base_seconds": game.time_control.base_seconds,
        "increment_seconds": game.time_control.increment_seconds,
    }


def _active_lobby_entry(game: Game) -> dict:
    live = game.live
    if live is not None:
        ply = live.ply
        to_move = "white" if live.board.turn == chess.WHITE else "black"
    else:  # PAIRED before the loop's first tick
        ply, to_move = 0, "white"
    return {
        "game_id": game.id,
        "state": game.state,
        "white": {"name": game.white.bot.name, "rating": game.white.bot.rating},
        "black": {"name": game.black.bot.name, "rating": game.black.bot.rating},
        "time_control": _tc(game),
        "ply": ply,
        "to_move": to_move,
        "started_at": game.created_at.isoformat(),
        "finished_at": None,
        "result": None,
        "termination": None,
    }


def _live_game_view(game: Game) -> dict:
    live = game.live
    return {
        "game_id": game.id,
        "state": game.state,
        "white": {
            "name": game.white.bot.name,
            "rating": game.white.bot.rating,
            "bot_id": game.white.bot.id,
        },
        "black": {
            "name": game.black.bot.name,
            "rating": game.black.bot.rating,
            "bot_id": game.black.bot.id,
        },
        "time_control": _tc(game),
        "initial_fen": game.initial_fen,
        "moves": list(live.moves) if live is not None else [],
        "result": game.result,
        "termination": game.termination,
        "final_fen": (
            game.final_fen
            if game.final_fen is not None
            else (live.board.fen() if live is not None else None)
        ),
        # A running/in-memory game has no persisted FinalizeResult; rating deltas
        # come from the durable record (finished path) instead.
        "rating": None,
    }


@router.get("/api/games")
async def list_games(request: Request) -> dict:
    registry = request.app.state.game_registry
    reader = getattr(request.app.state, "game_reader", None)
    limit = request.app.state.lobby_finished_limit
    active = [_active_lobby_entry(g) for g in registry.list_active()]
    finished = await reader.recent_finished(limit) if reader is not None else []
    return {"games": active + finished}


@router.get("/api/games/{game_id}")
async def get_game(game_id: str, request: Request) -> dict:
    registry = request.app.state.game_registry
    reader = getattr(request.app.state, "game_reader", None)

    game = registry.get(game_id)
    # A running game's authoritative state is in memory (ADR-0020).
    if game is not None and game.state in ("paired", "in_progress"):
        return _live_game_view(game)
    # Terminal or absent → prefer the durable record (carries the rating change).
    if reader is not None:
        view = await reader.get(game_id)
        if view is not None:
            return view
    # No DB (fast tests) but the finished game is still in memory → serve it.
    if game is not None and game.live is not None:
        return _live_game_view(game)
    raise HTTPException(status_code=404, detail="no such game")


# --- Per-bot game history (KAN-53) ---------------------------------------------
# A bot-perspective view over its FINISHED games: result becomes win/loss/draw for
# THIS bot (derived from the stored result + which color it played), the opponent
# is whoever sat the other seat, and the rating change is this bot's own colour's
# {before, after}. ABORTED rows have no result, so they're excluded (no W/L/D).

# Result strings stored on a decided game (models.Game.result); "aborted" is the
# only other value and is filtered out.
_DECIDED = ("white_wins", "black_wins", "draw")


def _bot_result(row: GameRow, is_white: bool) -> str:
    """win/loss/draw from THIS bot's seat, for a decided (non-aborted) game."""
    if row.result == "draw":
        return "draw"
    bot_won = row.result == ("white_wins" if is_white else "black_wins")
    return "win" if bot_won else "loss"


def _bot_game_entry(row: GameRow, bot_id: str) -> dict:
    """One finished game as a history item shaped from `bot_id`'s perspective."""
    is_white = row.white_bot_id == bot_id
    if is_white:
        color = "white"
        my_before, my_after = row.white_rating_before, row.white_rating_after
        opp_name, opp_id = row.black_name, row.black_bot_id
        opp_after, opp_before = row.black_rating_after, row.black_rating_before
    else:
        color = "black"
        my_before, my_after = row.black_rating_before, row.black_rating_after
        opp_name, opp_id = row.white_name, row.white_bot_id
        opp_after, opp_before = row.white_rating_after, row.white_rating_before
    rating = (
        {"before": my_before, "after": my_after}
        if my_before is not None and my_after is not None
        else None
    )
    return {
        "game_id": row.id,
        "color": color,
        "result": _bot_result(row, is_white),
        "opponent": {
            "bot_id": opp_id,
            "name": opp_name,
            # The opponent's post-game rating (falls back to pre-game if a game
            # somehow stored only the "before").
            "rating": opp_after if opp_after is not None else opp_before,
        },
        "rating": rating,
        "time_control": {
            "base_seconds": row.base_seconds,
            "increment_seconds": row.increment_seconds,
        },
        "termination": row.termination,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


async def _bot_history(session: AsyncSession, bot_id: str, limit: int) -> dict | None:
    """`None` if the bot is unknown; otherwise its history + W/L/D summary.

    The summary is aggregated over ALL the bot's decided games (independent of the
    `limit` that only trims the returned per-game list)."""
    bot = await session.get(BotRow, bot_id)
    if bot is None:
        return None

    plays = or_(GameRow.white_bot_id == bot_id, GameRow.black_bot_id == bot_id)
    decided = GameRow.result.in_(_DECIDED)
    win = or_(
        and_(GameRow.white_bot_id == bot_id, GameRow.result == "white_wins"),
        and_(GameRow.black_bot_id == bot_id, GameRow.result == "black_wins"),
    )
    loss = or_(
        and_(GameRow.white_bot_id == bot_id, GameRow.result == "black_wins"),
        and_(GameRow.black_bot_id == bot_id, GameRow.result == "white_wins"),
    )
    wins, losses, draws = (
        await session.execute(
            select(
                func.count().filter(win),
                func.count().filter(loss),
                func.count().filter(GameRow.result == "draw"),
            ).where(plays, decided)
        )
    ).one()

    rows = (
        (
            await session.execute(
                select(GameRow)
                .where(plays, decided)
                .order_by(GameRow.finished_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return {
        "bot": {"bot_id": bot.id, "name": bot.name},
        "summary": {
            "wins": int(wins),
            "losses": int(losses),
            "draws": int(draws),
            "games_played": bot.games_played,
            "rating": bot.rating,
        },
        "games": [_bot_game_entry(r, bot_id) for r in rows],
    }


@router.get("/api/bots/{bot_id}/games")
async def bot_game_history(
    bot_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """A bot's finished-game history (newest first) + a W/L/D summary (KAN-53).

    Public + read-only, like the lobby. Finished games are durable-only, so this
    reads through the request-scoped `get_async_session` DI seam (like
    `bots/routes.py` / the leaderboard); a bot not in the DB → 404."""
    limit = max(1, min(limit, 200))
    history = await _bot_history(session, bot_id, limit)
    if history is None:
        raise HTTPException(status_code=404, detail="no such bot")
    return history
