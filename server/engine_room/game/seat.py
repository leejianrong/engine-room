"""Seats make the game loop transport-agnostic (V1-plan D-f).

A WsSeat drives a real bot over its WebSocket (send your_turn, await a legal
move at the expected ply). A HouseSeat computes an in-process house-bot move.
The loop (worker.py) treats them identically: request_move -> confirm_move,
and game_over at the end.

V1 note: an out-of-turn ply, unparseable move, or illegal move is reported and
ignored (the clock keeps running); illegal-move *forfeit* is the V4 slice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import chess

from ..protocol.messages import (
    Clocks,
    Error,
    GameOver,
    Move,
    MoveAck,
    Rating,
    YourTurn,
)

if TYPE_CHECKING:
    from ..ws.session import Session
    from .house_bots import RandomBot


class WsSeat:
    def __init__(self, session: "Session", game_id: str, color: str, rating: int):
        self.session = session
        self.game_id = game_id
        self.color = color  # "white" | "black"
        self.rating = rating
        self._pending_id: Optional[str] = None

    async def request_move(
        self, board: chess.Board, ply: int, last_move: Optional[dict], clocks: Clocks
    ) -> str:
        await self.session.send(
            YourTurn(
                game_id=self.game_id,
                ply=ply,
                fen=board.fen(),
                last_move=last_move,
                clocks=clocks,
                your_color=self.color,
                opponent_draw_offer=False,
            )
        )
        while True:
            msg: Move = await self.session.inbound.get()
            if msg.ply != ply:
                await self.session.send(
                    Error(code="INVALID_PLY", message=f"expected ply {ply}")
                )
                continue
            try:
                move = chess.Move.from_uci(msg.uci)
            except ValueError:
                await self.session.send(Error(code="INVALID_MESSAGE", message="unparseable move"))
                continue
            if move not in board.legal_moves:
                # V1: ignored, clock keeps running. Illegal-move forfeit is V4.
                await self.session.send(Error(code="INVALID_MESSAGE", message="illegal move"))
                continue
            self._pending_id = msg.id
            return msg.uci

    async def confirm_move(self, ply: int) -> None:
        await self.session.send(
            MoveAck(id=self._pending_id, game_id=self.game_id, ply=ply, accepted=True)
        )

    async def game_over(self, result: str, termination: str, final_fen: str, pgn: str) -> None:
        await self.session.send(
            GameOver(
                game_id=self.game_id,
                result=result,
                termination=termination,
                final_fen=final_fen,
                pgn=pgn,
                rating=Rating(before=self.rating, after=self.rating),  # stubbed; real Elo in V5
            )
        )


class HouseSeat:
    def __init__(self, house: "RandomBot", game_id: str, color: str):
        self.house = house
        self.game_id = game_id
        self.color = color

    async def request_move(
        self, board: chess.Board, ply: int, last_move: Optional[dict], clocks: Clocks
    ) -> str:
        # In-process and instant; the house bot never needs a your_turn frame.
        return self.house.choose_move(board)

    async def confirm_move(self, ply: int) -> None:
        return None

    async def game_over(self, result: str, termination: str, final_fen: str, pgn: str) -> None:
        return None
