"""Spectator SSE endpoint (N9, ADR-0015) — anonymous, read-only.

Streams a live game's events as Server-Sent Events. V6 adds a **catch-up
snapshot** (ADR-0015 F5): the first event is a `snapshot` built from `game.live`
(current board/clocks/players + the full move-list-so-far), so a mid-game joiner
renders immediately and can replay from move 1; the live tail (move / game_over)
follows.

Ordering guarantees no lost events: we subscribe to the channel BEFORE reading
the snapshot, so a move published in the gap is queued in the tail. It may then
appear BOTH in the snapshot's `moves` and as the first tail `move` — the client
dedups by `ply` (ignore tail events with `ply < snapshot.ply`), mirroring V4's
ply-idempotency (V6 D-a). If there is no live state yet (a just-created PAIRED
game), the snapshot is omitted and the client falls back to `game_start`.
"""

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..channels import game_channel

router = APIRouter()


@router.get("/api/spectate/{game_id}")
async def spectate(game_id: str, request: Request) -> StreamingResponse:
    registry = request.app.state.game_registry
    pubsub = request.app.state.pubsub

    game = registry.get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="no such game")

    # Subscribe before returning so no event published between now and the first
    # stream iteration is lost.
    subscription = pubsub.subscribe(game_channel(game_id))

    async def event_stream():
        # Flush a comment immediately so the response opens (client EventSource
        # onopen fires) without waiting for the first game event.
        yield ": connected\n\n"
        # Catch-up: read the snapshot AFTER subscribing (no lost tail; a move in
        # the gap is also queued and deduped client-side by ply — V6 D-a).
        snapshot = game.spectator_snapshot()
        if snapshot is not None:
            yield f"data: {json.dumps(snapshot)}\n\n"
            # A game already terminal (still in memory) publishes no more tail
            # events — deliver its game_over and end the stream so we don't block
            # forever. (A live game falls through to the tail loop.)
            if game.state in ("finished", "aborted"):
                yield "data: " + json.dumps(
                    {
                        "type": "game_over",
                        "game_id": game.id,
                        "result": game.result,
                        "termination": game.termination,
                        "final_fen": game.final_fen,
                    }
                ) + "\n\n"
                subscription.close()
                return
        try:
            while True:
                event = await subscription.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "game_over":
                    return
        finally:
            subscription.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
