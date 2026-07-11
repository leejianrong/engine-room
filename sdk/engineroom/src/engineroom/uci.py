"""Client-side UCI bridge (ADR-0021 L2).

Point an existing UCI engine (e.g. Stockfish) at the platform without rewriting
it. ``UCIBot`` delegates ``choose_move`` to a local engine subprocess via
``python-chess``'s ``chess.engine`` — it runs entirely on the user's machine, so
it does NOT reintroduce native UCI on the server. Stockfish is not bundled; supply
your own engine binary.

    engineroom-uci --engine /usr/bin/stockfish --think-time 0.1

Reads ``ENGINEROOM_KEY`` / ``ENGINEROOM_URL`` from the environment like any bot
(the legacy ``CHESSROOM_*`` names are still accepted, deprecated — KAN-71).
"""

from __future__ import annotations

import argparse

import chess
import chess.engine

from .bot import Bot


class UCIBot(Bot):
    """A ``Bot`` whose moves come from a local UCI engine subprocess."""

    def __init__(
        self,
        engine_path: str,
        *args,
        think_time: float = 0.1,
        depth: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.engine_path = engine_path
        self.think_time = think_time
        self.depth = depth
        self._engine: chess.engine.SimpleEngine | None = None

    def _ensure_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
        return self._engine

    def choose_move(self, board: chess.Board) -> chess.Move:
        limit = (
            chess.engine.Limit(depth=self.depth)
            if self.depth is not None
            else chess.engine.Limit(time=self.think_time)
        )
        result = self._ensure_engine().play(board, limit)
        assert result.move is not None
        return result.move

    def close(self) -> None:
        """Shut down the engine subprocess (O-5: avoid orphaned processes)."""
        if self._engine is not None:
            try:
                self._engine.quit()
            finally:
                self._engine = None

    def run(self, *, loop: bool = False) -> None:
        try:
            super().run(loop=loop)
        finally:
            self.close()


def main() -> None:
    p = argparse.ArgumentParser(
        prog="engineroom-uci",
        description="Point a local UCI engine at Engine Room.",
    )
    p.add_argument("--engine", required=True, help="path to a UCI engine binary (e.g. stockfish)")
    p.add_argument("--think-time", type=float, default=0.1, dest="think_time",
                   help="seconds per move (default 0.1)")
    p.add_argument("--depth", type=int, default=None,
                   help="fixed search depth (overrides --think-time)")
    p.add_argument("--key", default=None, help="crbk_ API key (else ENGINEROOM_KEY)")
    p.add_argument("--url", default=None, help="WS URL (else ENGINEROOM_URL / the live platform)")
    p.add_argument("--base", type=int, default=180, help="clock base seconds (default 180)")
    p.add_argument("--inc", type=int, default=0, help="clock increment seconds (default 0)")
    p.add_argument("--loop", action="store_true", help="keep seeking new games")
    args = p.parse_args()

    bot = UCIBot(
        args.engine,
        key=args.key,
        url=args.url,
        think_time=args.think_time,
        depth=args.depth,
        time_control=(args.base, args.inc),
    )
    bot.run(loop=args.loop)


if __name__ == "__main__":
    main()
