"""The ``Bot`` base class and the run loop.

Subclass ``Bot``, implement ``choose_move(board)``, call ``run()``. The loop owns
the whole wire contract so the beginner never sees it: the authenticated handshake
(§3/§4), auto-seek (§5), the in-game exchange (§6), ``ply``-idempotent resends and
heartbeat pong (§9/§10), and reconnect-resume from ``welcome.active_game`` (§8).

The resilience logic is ported from ``engine_room.devtools.demo_bot`` (a proven
V4/V5 client) — see V7-plan.md P-a/P-f — but re-expressed as a library with a
swappable transport and no server imports (ADR-0021).
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional, Union

import chess

from ._config import ENV_KEY, env_key, env_url
from .const import (
    ACCEPT_DRAW,
    DEFAULT_URL,
    RESIGN,
    ConfigError,
    ProtocolError,
)
from .protocol import (
    GameOver,
    GameStart,
    TurnState,
    draw_accept_frame,
    hello_frame,
    move_frame,
    pong_frame,
    resign_frame,
    seek_frame,
)
from .transport import Transport, TransportClosed, WebSocketTransport

# A user's choose_move may return a move (chess.Move or UCI str) or a control
# sentinel (RESIGN / ACCEPT_DRAW).
Decision = Union[chess.Move, str, object]


class _GameEnded(Exception):
    """Internal: the game ended (e.g. flagged) while we were reconnecting."""


class Bot:
    """Base class for an Engine Room bot.

    Override :meth:`choose_move`. Optionally override :meth:`on_game_start` /
    :meth:`on_game_over`. Then call :meth:`run`.

    Config resolves from arguments first, then the environment: ``ENGINEROOM_KEY``
    (required) and ``ENGINEROOM_URL`` (defaults to the live platform). The legacy
    ``CHESSROOM_KEY`` / ``CHESSROOM_URL`` names are still accepted (deprecated,
    warned once) — KAN-71.
    """

    def __init__(
        self,
        key: Optional[str] = None,
        url: Optional[str] = None,
        *,
        time_control: tuple[int, int] = (180, 0),
        connect: Optional[Callable[[], Awaitable[Transport]]] = None,
    ) -> None:
        self.key = key or env_key()
        self.url = url or env_url() or DEFAULT_URL
        # The bot's display name/identity is set server-side from its API key
        # (created in the dashboard); there is no client-declared name (hello
        # carries only protocol_version + sdk, PROTOCOL §4).
        self.time_control = time_control
        # Injectable transport factory (tests). Defaults to a real WebSocket.
        self._connect_factory = connect
        # Tunables (small in tests): resend a move if no forward progress arrives
        # within _ack_timeout seconds (§9); bound total resends; reconnect backoff.
        self._ack_timeout: Optional[float] = 10.0
        self._max_resends = 3
        self._reconnect_attempts = 5
        self._reconnect_backoff = 0.5
        self._t: Optional[Transport] = None

    # ------------------------------------------------------------------ hooks
    def choose_move(self, board: chess.Board) -> Decision:
        """Return the move to play as a ``chess.Move`` or a UCI string, or a
        control sentinel (``engineroom.RESIGN`` / ``engineroom.ACCEPT_DRAW``)."""
        raise NotImplementedError

    def on_game_start(self, info: GameStart) -> None:  # noqa: D401 - optional hook
        """Called once when a game begins (override optionally)."""

    def on_game_over(self, result: GameOver) -> None:  # noqa: D401 - optional hook
        """Called once when a game ends (override optionally)."""

    # ----------------------------------------------------------------- public
    def run(self, *, loop: bool = False) -> None:
        """Connect and play. With ``loop=True``, keep seeking new games forever
        (the looping demo / house-bot pattern). Blocking; owns the event loop."""
        asyncio.run(self._run(loop=loop))

    # ------------------------------------------------------------- run loop
    async def _run(self, *, loop: bool) -> None:
        if not self.key:
            raise ConfigError(
                f"No API key. Set {ENV_KEY} (e.g. in .env) or pass Bot(key=...)."
            )
        while True:
            await self._play_one_game()
            if not loop:
                return

    async def _open(self) -> dict:
        """Open a fresh transport and complete the hello handshake; return the
        ``welcome`` (which may carry ``active_game`` on reconnect, §8)."""
        if self._connect_factory is not None:
            self._t = await self._connect_factory()
        else:
            self._t = await WebSocketTransport.connect(self.url, self.key)  # type: ignore[arg-type]
        await self._t.send(hello_frame())
        welcome = await self._t.recv()
        if welcome.get("type") != "welcome":
            code = welcome.get("code")
            if code == "VERSION_UNSUPPORTED":
                raise ProtocolError(
                    "Server rejected this SDK's protocol version — upgrade engineroom."
                )
            raise ProtocolError(f"handshake failed: {welcome}")
        return welcome

    async def _open_with_retry(self) -> dict:
        last: Exception | None = None
        for attempt in range(self._reconnect_attempts):
            try:
                return await self._open()
            except TransportClosed as exc:  # pragma: no cover - network flake path
                last = exc
                await asyncio.sleep(self._reconnect_backoff * (attempt + 1))
        raise ProtocolError(f"could not reconnect: {last}")

    async def _play_one_game(self) -> None:
        welcome = await self._open()
        try:
            active = welcome.get("active_game")
            if active:
                # Reconnected into an in-progress game (§8). The server re-sends
                # your_turn if it's our move; otherwise we wait for it.
                game_id = active["game_id"]
                self.on_game_start(GameStart.from_active_game(active))
                turn = await self._recv_turn()
            else:
                await self._t.send(seek_frame(*self.time_control))  # type: ignore[union-attr]
                start = await self._await_game_start()
                game_id = start.game_id
                self.on_game_start(start)
                turn = await self._recv_turn()
            await self._play_turns(game_id, turn)
        except _GameEnded:
            pass
        finally:
            if self._t is not None:
                await self._t.close()

    async def _play_turns(self, game_id: str, turn: dict) -> None:
        while True:
            if turn["type"] == "game_over":
                self.on_game_over(GameOver.from_msg(turn))
                return
            state = TurnState.from_msg(turn)
            decision = self._decide(state)
            if decision is RESIGN:
                await self._t.send(resign_frame(game_id))  # type: ignore[union-attr]
                turn = await self._recv_turn()
                continue
            if decision is ACCEPT_DRAW:
                await self._t.send(draw_accept_frame(game_id))  # type: ignore[union-attr]
                turn = await self._recv_turn()
                continue
            uci = decision.uci() if isinstance(decision, chess.Move) else str(decision)
            turn = await self._send_move(game_id, state.ply, uci)

    def _decide(self, state: TurnState) -> Decision:
        board = chess.Board(state.fen)
        # `board` already reflects the standing draw offer via
        # state.opponent_draw_offer; the bot decides by what it returns.
        return self.choose_move(board)

    # --------------------------------------------------------------- framing
    async def _recv(self, *, timeout: Optional[float] = None) -> dict:
        """Read the next frame, transparently answering heartbeat pings (§10)."""
        while True:
            if timeout is None:
                msg = await self._t.recv()  # type: ignore[union-attr]
            else:
                msg = await asyncio.wait_for(self._t.recv(), timeout)  # type: ignore[union-attr]
            if msg.get("type") == "ping":
                await self._t.send(pong_frame(msg.get("t", 0)))  # type: ignore[union-attr]
                continue
            return msg

    async def _recv_turn(self) -> dict:
        """Read until the next actionable frame — your_turn or game_over —
        skipping move_ack / seek_ack / non-fatal errors."""
        while True:
            msg = await self._recv()
            kind = msg["type"]
            if kind in ("your_turn", "game_over"):
                return msg
            if kind == "error" and msg.get("fatal"):
                raise ProtocolError(f"fatal error: {msg}")

    async def _await_game_start(self) -> GameStart:
        """Wait for game_start, skipping seek_ack and any *stale* game_over left
        over from a prior game (delivered on connect, V4 D-vi)."""
        while True:
            msg = await self._recv()
            kind = msg.get("type")
            if kind == "game_start":
                return GameStart.from_msg(msg)
            if kind == "error" and msg.get("fatal"):
                raise ProtocolError(f"fatal error while seeking: {msg}")

    async def _send_move(self, game_id: str, ply: int, uci: str) -> dict:
        """Send a move and return the next actionable frame. Resilient to:
        - a lost ack / silent drop → resend the SAME frame (idempotent, §9);
        - a dropped socket → reconnect and resume (§8)."""
        frame = move_frame(game_id, ply, uci)
        resends = 0
        await self._t.send(frame)  # type: ignore[union-attr]
        while True:
            try:
                msg = await self._recv(timeout=self._ack_timeout)
            except TransportClosed:
                turn = await self._reconnect_resume(game_id)
                if turn is None:
                    raise _GameEnded
                return turn
            except asyncio.TimeoutError:
                if resends >= self._max_resends:
                    raise ProtocolError("no response from server after resends")
                resends += 1
                await self._t.send(frame)  # idempotent resend (§9)  # type: ignore[union-attr]
                continue
            kind = msg["type"]
            if kind == "move_ack":
                continue  # got our ack; keep reading for the resulting turn
            if kind in ("your_turn", "game_over"):
                return msg
            if kind == "error":
                if msg.get("fatal"):
                    raise ProtocolError(f"fatal error: {msg}")
                # NOT_YOUR_TURN / INVALID_PLY (a late/dup) — ignore, keep reading.
                continue

    async def _reconnect_resume(self, game_id: str) -> Optional[dict]:
        """Re-open the socket and resume the live game from welcome.active_game
        (§8). Return the your_turn/game_over to act on, or None if the game is no
        longer active (it ended while we were away)."""
        welcome = await self._open_with_retry()
        active = welcome.get("active_game")
        if active and active.get("game_id") == game_id:
            return await self._recv_turn()
        return None
