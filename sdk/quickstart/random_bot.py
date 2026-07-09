"""Your first Engine Room bot.

A RandomBot: it plays a uniformly-random legal move. That's the whole bot — the
`chessroom` SDK handles the connection, matchmaking, clocks, reconnects, and the
wire protocol for you.

Run it:

    cp .env.example .env      # then paste your CHESSROOM_KEY into .env
    uv sync
    uv run python random_bot.py

Then open the dashboard and watch your bot play. To make it smarter, replace the
body of `choose_move` — it's handed a python-chess `Board` and returns a move.
"""

import random

from dotenv import load_dotenv

from chessroom import Bot

load_dotenv()  # read CHESSROOM_KEY / CHESSROOM_URL from .env


class RandomBot(Bot):
    def choose_move(self, board):
        return random.choice(list(board.legal_moves))


if __name__ == "__main__":
    # loop=True keeps seeking new games after each one finishes. Your bot's name
    # in the lobby is the one you gave it in the dashboard.
    RandomBot().run(loop=True)
