"""Spectator read REST (V6, N9 / ADR-0015 F3+F5) — anonymous, read-only, CORS
like the SSE endpoint.

- `GET /api/games` — the lobby: active/paired games from the in-memory registry
  (ADR-0020) merged with the most-recently-finished games from Postgres (D-e).
- `GET /api/games/{id}` — the replay/detail view: a running game is projected
  from `LiveState`; a finished game from its stored PGN (D-d). One uniform
  `[{ply, san, uci, fen}]` move-list either way, so the client has ONE replay
  model.

Both degrade gracefully when no `game_reader` is injected (fast, DB-free tests):
the lobby returns active games only; the detail serves an in-memory game or 404s.
"""

from __future__ import annotations

import chess
from fastapi import APIRouter, HTTPException, Request

from ..game.game import Game

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
