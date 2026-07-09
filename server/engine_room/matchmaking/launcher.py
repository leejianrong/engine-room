"""GameLauncher (D-c) — turns a freshly-created Game into a running game.

Sends `game_start` to each live human seat (from that seat's perspective) and
spawns the `run_game` task, holding a strong ref so it isn't GC'd. This logic
used to live inline in the WS endpoint; V3 moves it here so the **matcher** can
launch a game it paired (the endpoint no longer owns game spawning), and so the
greeter-fallback path reuses exactly the same launch.

Injected via `create_app`/`app.state`, mirroring the finalizer DI.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from ..game.game import Game
from ..game.worker import run_game
from ..protocol.messages import Clocks, GameStart

if TYPE_CHECKING:
    from ..game.worker import Finalizer
    from ..pubsub.base import PubSub


def game_start_for(game: Game, color: str) -> GameStart:
    """Build `game_start` from the given seat's perspective (PROTOCOL.md §5)."""
    if color == "white":
        opponent = game.black.bot
    else:
        opponent = game.white.bot
    return GameStart(
        game_id=game.id,
        your_color=color,
        opponent=opponent,
        time_control=game.time_control,
        initial_fen=game.initial_fen,
        clocks=Clocks(white_ms=game.white_ms, black_ms=game.black_ms),
    )


class GameLauncher:
    def __init__(self, pubsub: "PubSub", finalizer: Optional["Finalizer"] = None) -> None:
        self._pubsub = pubsub
        self._finalizer = finalizer
        # Strong refs to in-flight game tasks so they aren't garbage-collected.
        self._tasks: set[asyncio.Task] = set()

    async def launch(self, game: Game) -> None:
        """Notify both bots, then start the game loop as a background task.

        `game_start` is sent (and awaited) before the task is created, so a bot
        always sees `game_start` before its first `your_turn` (§5). House seats
        have no session and are skipped."""
        for participant, color in ((game.white, "white"), (game.black, "black")):
            if participant.session is not None:
                await participant.session.send(game_start_for(game, color))
        task = asyncio.create_task(run_game(game, self._pubsub, self._finalizer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
