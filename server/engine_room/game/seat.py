"""Seats make the game loop transport-agnostic (V1-plan D-f).

A WsSeat drives a real bot over its WebSocket (send your_turn, await a legal
move at the expected ply). A HouseSeat computes an in-process house-bot move.
The loop (worker.py) treats them identically: request_move -> confirm_move,
and game_over at the end.

V4 (resilience): the read loop is `ply`-idempotent (PROTOCOL §9) — a duplicate
resend at an already-applied ply is re-acked (never re-applied), a stale
conflicting resend is ignored (not penalized), and a future ply is rejected
(INVALID_PLY). An illegal/unparseable move AT the current ply is now an instant
**forfeit** (ADR-0016 B7) — raised as `IllegalMoveForfeit` for the loop to turn
into game_over{termination:"illegal_move"} (V1 reported-and-ignored it). All
outbound sends are best-effort: a dead/half-dead socket must never crash the
game loop — the clock is the sole arbiter (ADR-0025 #3), so a bot whose frame
couldn't be delivered simply reconnects or flags.
"""

from __future__ import annotations

import asyncio
import contextlib
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


class IllegalMoveForfeit(Exception):
    """Raised by a WsSeat when the move AT the current ply is illegal or
    unparseable (ADR-0016 B7). run_game turns it into a game_over with
    termination "illegal_move" (the offending `color` loses)."""

    def __init__(self, color: str):
        super().__init__(f"{color} played an illegal move")
        self.color = color


class WsSeat:
    def __init__(self, session: "Session", game_id: str, color: str, rating: int):
        self.session = session
        self.game_id = game_id
        self.color = color  # "white" | "black"
        self.rating = rating
        self._pending_id: Optional[str] = None
        # Whether the move just returned by request_move carried a piggybacked
        # draw offer (Move.offer_draw, §6/D6). The worker reads it after applying.
        self._offer_draw: bool = False
        # The seat owns its inbound move queue (V4 D-i): it is the bot's durable
        # game-side identity (ADR-0009), so a blocked `get()` survives a
        # newest-wins session swap on reconnect. The endpoint routes `move`
        # frames here (via the active-game index); `session` is swapped by
        # `rebind()` on reconnect and is used only for outbound frames.
        self.inbound: asyncio.Queue = asyncio.Queue()

    def rebind(self, session: "Session") -> None:
        """Point outbound at the reconnected session (newest-wins). The inbound
        queue is unchanged, so an in-flight `request_move` keeps working."""
        self.session = session

    async def resend_your_turn(self, live) -> None:
        """Re-send `your_turn` after a reconnect when it is this seat's move — the
        original went to the now-dead socket (PROTOCOL §8). Best-effort."""
        await self._send(
            YourTurn(
                game_id=self.game_id,
                ply=live.ply,
                fen=live.board.fen(),
                last_move=live.last_move,
                clocks=Clocks(
                    white_ms=live.clock.remaining_ms(chess.WHITE),
                    black_ms=live.clock.remaining_ms(chess.BLACK),
                ),
                your_color=self.color,
                opponent_draw_offer=(
                    live.pending_draw_offer is not None
                    and live.pending_draw_offer != self.color
                ),
            )
        )

    async def _send(self, message) -> None:
        """Best-effort outbound (D-b): a dead socket must not crash run_game."""
        with contextlib.suppress(Exception):
            await self.session.send(message)

    async def request_move(
        self,
        board: chess.Board,
        ply: int,
        last_move: Optional[dict],
        clocks: Clocks,
        applied: Optional[dict[int, str]] = None,
        opponent_draw_offer: bool = False,
    ) -> str:
        applied = applied or {}
        await self._send(
            YourTurn(
                game_id=self.game_id,
                ply=ply,
                fen=board.fen(),
                last_move=last_move,
                clocks=clocks,
                your_color=self.color,
                opponent_draw_offer=opponent_draw_offer,
            )
        )
        while True:
            msg: Move = await self.inbound.get()
            if msg.ply == ply:
                # The move for the current ply. Illegal/unparseable → forfeit (B7).
                try:
                    move = chess.Move.from_uci(msg.uci)
                except ValueError:
                    raise IllegalMoveForfeit(self.color)
                if move not in board.legal_moves:
                    raise IllegalMoveForfeit(self.color)
                self._pending_id = msg.id
                self._offer_draw = bool(msg.offer_draw)  # piggybacked draw offer (D6)
                return msg.uci
            if msg.ply < ply:
                # A past ply (§9): a blind resend after a blip.
                if applied.get(msg.ply) == msg.uci:
                    # Duplicate of what we already applied → re-ack, do NOT re-apply.
                    await self._send(
                        MoveAck(
                            id=msg.id, game_id=self.game_id, ply=msg.ply, accepted=True
                        )
                    )
                # else: stale/conflicting late duplicate → ignore, NOT penalized.
                continue
            # msg.ply > ply → from the future (§9): reject, keep waiting.
            await self._send(Error(code="INVALID_PLY", message=f"expected ply {ply}"))

    async def confirm_move(self, ply: int) -> None:
        await self._send(
            MoveAck(id=self._pending_id, game_id=self.game_id, ply=ply, accepted=True)
        )

    async def game_over(self, result: str, termination: str, final_fen: str, pgn: str) -> None:
        await self._send(
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
    def __init__(self, house: "RandomBot", game_id: str, color: str, delay: float = 0.0):
        self.house = house
        self.game_id = game_id
        self.color = color
        self.delay = delay  # optional pause so house moves are watchable (dev)

    async def request_move(
        self,
        board: chess.Board,
        ply: int,
        last_move: Optional[dict],
        clocks: Clocks,
        applied: Optional[dict[int, str]] = None,
        opponent_draw_offer: bool = False,
    ) -> str:
        # In-process; the house bot never needs a your_turn frame and never
        # resends, so `applied` (§9 idempotency) is irrelevant here. An optional
        # delay (await, so the loop isn't blocked) paces moves for spectators and
        # is charged to the house's own clock.
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.house.choose_move(board)

    async def confirm_move(self, ply: int) -> None:
        return None

    async def game_over(self, result: str, termination: str, final_fen: str, pgn: str) -> None:
        return None
