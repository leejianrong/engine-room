"""Pub/sub channel naming. Kept neutral so the pubsub layer stays game-agnostic."""


def game_channel(game_id: str) -> str:
    return f"game:{game_id}"
