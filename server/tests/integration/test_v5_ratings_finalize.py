"""V5: real Elo written atomically with the game record (ADR-0025 #5).

A decisive game moves BOTH bots' `bots.rating`, increments `games_played`, and
writes the four per-color `games` rating columns — all in one finalize
transaction. An ABORTED game writes NULL rating columns and leaves ratings
unchanged. Uses the ephemeral testcontainers Postgres; the game is driven to a
deterministic terminal via a blocking seat + the control channel (house bots are
random, so a natural decisive result isn't deterministic)."""

import asyncio
from datetime import datetime, timezone

import chess

from engine_room.game.clock import Clock
from engine_room.game.game import LiveState, Participant
from engine_room.game.house_bots import EPHRAIM_ID, RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import run_game
from engine_room.persistence.finalize import PostgresFinalizer
from engine_room.persistence.models import Bot
from engine_room.persistence.models import Game as GameRow
from engine_room.persistence.seed import seed_house_bots
from engine_room.protocol.messages import Resign, TimeControl
from engine_room.pubsub.inproc import InProcPubSub


class _BlockingSeat:
    """A seat that never returns a move (so the game ends only via a control or an
    abort) and records the rating it is handed at game_over."""

    def __init__(self, color: str):
        self.color = color
        self.rating_over = None

    async def request_move(self, *a, **k):
        await asyncio.Event().wait()

    async def confirm_move(self, ply):
        return None

    async def game_over(self, result, termination, final_fen, pgn,
                        rating_before=None, rating_after=None):
        self.rating_over = (rating_before, rating_after)


async def _seed(session_factory):
    async with session_factory() as session:
        await seed_house_bots(session)  # bot_ephraim @ 1200, games_played 0
        session.add(
            Bot(
                id="bot_user1",
                name="alice",
                description="",
                rating=1200,
                is_house=True,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


def _scripted_game(registry: GameRegistry):
    white = RandomBot(id="bot_user1", name="alice")
    black = RandomBot()  # canonical house bot (ephraim)
    game = registry.create_game(
        white=Participant(bot=white.info, is_house=True, house=white),
        black=Participant(bot=black.info, is_house=True, house=black),
        time_control=TimeControl(base_seconds=180),
    )
    ws, bs = _BlockingSeat("white"), _BlockingSeat("black")
    game.seats = {"white": ws, "black": bs}
    game.live = LiveState(board=chess.Board(), clock=Clock(game.white_ms, game.black_ms))
    return game, ws, bs


async def test_decisive_game_moves_ratings_in_one_txn(session_factory):
    await _seed(session_factory)
    registry = GameRegistry()
    game, ws, bs = _scripted_game(registry)
    # White (alice) resigns → Black (house) wins.
    game.controls.put_nowait(("white", Resign(type="resign", game_id=game.id)))

    result, termination = await run_game(
        game, InProcPubSub(), PostgresFinalizer(session_factory)
    )
    assert (result, termination) == ("black_wins", "resignation")

    async with session_factory() as session:
        alice = await session.get(Bot, "bot_user1")
        house = await session.get(Bot, EPHRAIM_ID)
        row = await session.get(GameRow, game.id)

    # 1200 vs 1200, provisional K=32: loser 1200-16=1184, winner 1200+16=1216.
    assert (alice.rating, alice.games_played) == (1184, 1)
    assert (house.rating, house.games_played) == (1216, 1)
    # The four rating columns were written in the same row/txn.
    assert (row.white_rating_before, row.white_rating_after) == (1200, 1184)
    assert (row.black_rating_before, row.black_rating_after) == (1200, 1216)
    # game_over carried the same persisted numbers.
    assert ws.rating_over == (1200, 1184)
    assert bs.rating_over == (1200, 1216)


async def test_aborted_game_writes_no_rating(session_factory):
    await _seed(session_factory)
    registry = GameRegistry()
    game, ws, bs = _scripted_game(registry)
    game.abort.set()  # both-gone → ABORTED before any move

    result, termination = await run_game(
        game, InProcPubSub(), PostgresFinalizer(session_factory)
    )
    assert (result, termination) == ("aborted", "aborted")

    async with session_factory() as session:
        alice = await session.get(Bot, "bot_user1")
        house = await session.get(Bot, EPHRAIM_ID)
        row = await session.get(GameRow, game.id)

    assert (alice.rating, alice.games_played) == (1200, 0)  # unchanged
    assert (house.rating, house.games_played) == (1200, 0)
    assert row.white_rating_before is None and row.white_rating_after is None
    assert row.black_rating_before is None and row.black_rating_after is None
    assert ws.rating_over == (None, None)  # game_over.rating omitted for aborted
