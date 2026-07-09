"""V6 sub-step 3 (integration, real Postgres): the spectator game_over SSE event
carries the persisted Elo change (Q6/D-f); an ABORTED game omits it.

Drives a deterministic decisive terminal via a blocking seat + the control channel
(house bots are random), reusing the V5 finalize-test scaffolding, and reads the
game's pubsub channel directly (the SSE endpoint publishes this exact event)."""

import asyncio
from datetime import datetime, timezone

import chess

from engine_room.channels import game_channel
from engine_room.game.clock import Clock
from engine_room.game.game import LiveState, Participant
from engine_room.game.house_bots import RandomBot
from engine_room.game.registry import GameRegistry
from engine_room.game.worker import run_game
from engine_room.persistence.finalize import PostgresFinalizer
from engine_room.persistence.models import Bot
from engine_room.persistence.seed import seed_house_bots
from engine_room.protocol.messages import Resign, TimeControl
from engine_room.pubsub.inproc import InProcPubSub


class _BlockingSeat:
    def __init__(self, color: str):
        self.color = color

    async def request_move(self, *a, **k):
        await asyncio.Event().wait()

    async def confirm_move(self, ply):
        return None

    async def game_over(self, *a, **k):
        return None


async def _seed(session_factory):
    async with session_factory() as session:
        await seed_house_bots(session)  # ephraim + jian-bot-001/002 @ 1200
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
    black = RandomBot()  # canonical house bot
    game = registry.create_game(
        white=Participant(bot=white.info, is_house=True, house=white),
        black=Participant(bot=black.info, is_house=True, house=black),
        time_control=TimeControl(base_seconds=180),
    )
    game.seats = {"white": _BlockingSeat("white"), "black": _BlockingSeat("black")}
    game.live = LiveState(board=chess.Board(), clock=Clock(game.white_ms, game.black_ms))
    return game


async def _drain_to_game_over(sub) -> dict:
    while True:
        ev = await sub.get()
        if ev["type"] == "game_over":
            return ev


async def test_sse_game_over_carries_rating(session_factory):
    await _seed(session_factory)
    registry = GameRegistry()
    game = _scripted_game(registry)
    pubsub = InProcPubSub()
    sub = pubsub.subscribe(game_channel(game.id))
    game.controls.put_nowait(("white", Resign(type="resign", game_id=game.id)))

    result, termination = await run_game(game, pubsub, PostgresFinalizer(session_factory))
    assert (result, termination) == ("black_wins", "resignation")

    ev = await _drain_to_game_over(sub)
    # 1200 vs 1200, provisional K=32: loser 1184, winner 1216.
    assert ev["rating"] == {
        "white": {"before": 1200, "after": 1184},
        "black": {"before": 1200, "after": 1216},
    }


async def test_sse_game_over_of_aborted_game_omits_rating(session_factory):
    await _seed(session_factory)
    registry = GameRegistry()
    game = _scripted_game(registry)
    pubsub = InProcPubSub()
    sub = pubsub.subscribe(game_channel(game.id))
    game.abort.set()  # both-gone → ABORTED

    result, _ = await run_game(game, pubsub, PostgresFinalizer(session_factory))
    assert result == "aborted"

    ev = await _drain_to_game_over(sub)
    assert "rating" not in ev
