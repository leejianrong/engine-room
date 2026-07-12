"""An in-memory fake server speaking the Engine Room wire protocol.

Lets the SDK run loop be exercised end-to-end with NO network: a ``FakeServer``
plays the Black side (random legal moves) against the bot (White) over a paired
in-memory transport, and can inject the adversarial conditions the SDK must
survive — a mid-game socket drop (→ reconnect-resume, §8), a silently dropped
move (→ idempotent resend, §9), and heartbeat pings (§10).

This deliberately re-implements just enough of the protocol from the spec; the
real server is exercised by the live-uvicorn contract test (V7 sub-step 3).
"""

from __future__ import annotations

import asyncio
import random

import chess

from engineroom.transport import Transport, TransportClosed

_CLOSE = object()


class _Endpoint:
    """One end of an in-memory duplex link. send→peer's inbox; recv←own inbox."""

    def __init__(self, inbox: asyncio.Queue, outbox: asyncio.Queue) -> None:
        self._in = inbox
        self._out = outbox
        self._closed = False

    async def send(self, message: dict) -> None:
        if self._closed:
            raise TransportClosed("send on closed transport")
        await self._out.put(message)

    async def recv(self) -> dict:
        msg = await self._in.get()
        if msg is _CLOSE:
            self._closed = True
            raise TransportClosed("peer closed")
        return msg

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._out.put(_CLOSE)


def _make_link() -> tuple[_Endpoint, _Endpoint]:
    a: asyncio.Queue = asyncio.Queue()
    b: asyncio.Queue = asyncio.Queue()
    return _Endpoint(a, b), _Endpoint(b, a)


class FakeServer:
    """A stateful mini-server. State (board, expected ply, over) persists across
    connections so reconnect can resume (§8). The bot plays White."""

    def __init__(
        self,
        *,
        max_plies: int = 10,
        seed: int = 0,
        drop_after_bot_moves: int | None = None,
        withhold_moves: int = 0,
        ping_before_turn: bool = False,
        offer_draw: bool = False,
        final: tuple[str, str] = ("draw", "agreement"),
    ) -> None:
        self.game_id = "game_fake"
        self.board = chess.Board()
        self.expected_ply = 0
        self.started = False
        self.over = False
        self.max_plies = max_plies
        self._rng = random.Random(seed)
        self.drop_after_bot_moves = drop_after_bot_moves
        self._dropped = False
        self.withhold_moves = withhold_moves
        self.ping_before_turn = ping_before_turn
        # When True, every your_turn carries a standing opponent draw offer (§7)
        # so the SDK can surface it to choose_move (KAN-84).
        self.offer_draw = offer_draw
        self.final = final
        # Observability for assertions.
        self.moves_received: list[tuple[int, str]] = []  # (ply, uci)
        self.bot_move_count = 0
        self.connections = 0
        self.resigned = False
        self.draw_agreed = False
        self._tasks: list[asyncio.Task] = []

    # -- transport factory the Bot connects through -----------------------
    async def connect(self) -> Transport:
        bot_ep, srv_ep = _make_link()
        self.connections += 1
        self._tasks.append(asyncio.create_task(self._serve(srv_ep)))
        return bot_ep

    # -- frame helpers -----------------------------------------------------
    def _clocks(self) -> dict:
        return {"white_ms": 180000, "black_ms": 180000}

    def _active_payload(self) -> dict:
        return {
            "game_id": self.game_id,
            "your_color": "white",
            "fen": self.board.fen(),
            "ply": self.expected_ply,
            "last_move": None,
            "clocks": self._clocks(),
            "opponent_draw_offer": False,
            "to_move": "white" if self.board.turn == chess.WHITE else "black",
        }

    def _your_turn(self, last_move: dict | None) -> dict:
        return {
            "type": "your_turn",
            "game_id": self.game_id,
            "ply": self.expected_ply,
            "fen": self.board.fen(),
            "last_move": last_move,
            "clocks": self._clocks(),
            "your_color": "white",
            "opponent_draw_offer": self.offer_draw,
        }

    def _game_over(self, result: str, termination: str) -> dict:
        self.over = True
        return {
            "type": "game_over",
            "game_id": self.game_id,
            "result": result,
            "termination": termination,
            "final_fen": self.board.fen(),
            "pgn": "[Event \"fake\"]\n",
            "rating": {"before": 1200, "after": 1208},
        }

    def _terminal_now(self) -> dict | None:
        if self.board.is_game_over():
            outcome = self.board.outcome()
            if outcome is None:
                return None
            if outcome.winner is None:
                return self._game_over("draw", "stalemate")
            return self._game_over(
                "white_wins" if outcome.winner == chess.WHITE else "black_wins", "checkmate"
            )
        if len(self.board.move_stack) >= self.max_plies:
            return self._game_over(*self.final)
        return None

    async def _serve(self, ep: _Endpoint) -> None:
        try:
            hello = await ep.recv()
            assert hello.get("type") == "hello"
            active = self._active_payload() if (self.started and not self.over) else None
            await ep.send(
                {
                    "type": "welcome",
                    "protocol_version": "1.0",
                    "session_id": "sess_fake",
                    "bot": {"id": "bot_fake", "name": "fake-bot", "rating": 1200},
                    "active_game": active,
                }
            )
            # On resume, if it's our (White's) turn, the server re-sends your_turn.
            if active and self.board.turn == chess.WHITE:
                await self._maybe_ping(ep)
                await ep.send(self._your_turn(None))

            while True:
                msg = await ep.recv()
                await self._handle(ep, msg)
        except TransportClosed:
            return
        except asyncio.CancelledError:  # pragma: no cover - teardown
            return

    async def _maybe_ping(self, ep: _Endpoint) -> None:
        if self.ping_before_turn:
            await ep.send({"type": "ping", "t": 42})

    async def _handle(self, ep: _Endpoint, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "pong" or kind == "seek_cancel":
            return
        if kind == "seek":
            self.started = True
            self.expected_ply = 0
            await ep.send(
                {"type": "seek_ack", "id": msg.get("id"), "seek_id": "seek_1", "status": "queued"}
            )
            await ep.send(
                {
                    "type": "game_start",
                    "game_id": self.game_id,
                    "your_color": "white",
                    "opponent": {"id": "bot_house_random", "name": "house-random", "rating": 1200},
                    "time_control": {"base_seconds": 180, "increment_seconds": 0},
                    "initial_fen": self.board.fen(),
                    "clocks": self._clocks(),
                    "start_grace_ms": 10000,
                }
            )
            await self._maybe_ping(ep)
            await ep.send(self._your_turn(None))
            return
        if kind == "resign":
            self.resigned = True
            await ep.send(self._game_over("black_wins", "resignation"))
            return
        if kind == "draw_accept":
            self.draw_agreed = True
            await ep.send(self._game_over("draw", "agreement"))
            return
        if kind == "move":
            await self._handle_move(ep, msg)
            return

    async def _handle_move(self, ep: _Endpoint, msg: dict) -> None:
        self.moves_received.append((msg["ply"], msg["uci"]))
        # Simulate a silently-dropped move: read it, do nothing (the SDK will
        # resend the identical frame after its ack timeout, §9).
        if self.withhold_moves > 0:
            self.withhold_moves -= 1
            return
        if msg["ply"] != self.expected_ply:
            # Not the current ply — ack idempotently without re-applying (§9).
            await ep.send({"type": "move_ack", "id": msg.get("id"), "game_id": self.game_id,
                           "ply": msg["ply"], "accepted": True})
            return
        move = chess.Move.from_uci(msg["uci"])
        self.board.push(move)
        self.bot_move_count += 1
        self.expected_ply += 1
        await ep.send({"type": "move_ack", "id": msg.get("id"), "game_id": self.game_id,
                       "ply": msg["ply"], "accepted": True})
        over = self._terminal_now()
        if over:
            await ep.send(over)
            return
        # Black (the "house") replies with a random legal move.
        reply = self._rng.choice(list(self.board.legal_moves))
        self.board.push(reply)
        self.expected_ply += 1
        last = {"uci": reply.uci(), "san": "?"}
        over = self._terminal_now()
        if over:
            await ep.send(over)
            return
        # Arm a mid-game drop: close instead of sending the next your_turn.
        if (
            self.drop_after_bot_moves is not None
            and self.bot_move_count == self.drop_after_bot_moves
            and not self._dropped
        ):
            self._dropped = True
            await ep.close()
            return
        await self._maybe_ping(ep)
        await ep.send(self._your_turn(last))
