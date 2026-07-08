"""Spectator SSE endpoint (N9, ADR-0015) — anonymous, read-only.

Streams a live game's events (move / game_over) as Server-Sent Events. V1 has
no catch-up snapshot or replay (those are V6): a spectator sees events from the
moment it connects onward.
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

    if registry.get(game_id) is None:
        raise HTTPException(status_code=404, detail="no such game")

    # Subscribe before returning so no event published between now and the first
    # stream iteration is lost.
    subscription = pubsub.subscribe(game_channel(game_id))

    async def event_stream():
        # Flush a comment immediately so the response opens (client EventSource
        # onopen fires) without waiting for the first game event.
        yield ": connected\n\n"
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
