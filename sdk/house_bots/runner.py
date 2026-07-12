"""Out-of-process house-bot runner (KAN-61) — an `engineroom` SDK WebSocket client.

The server (with ``ER_HOUSE_BOTS_OUT_OF_PROCESS=true``) spawns one of these per
permanent ambient house identity (jian-bot-001 / jian-bot-002). It is a *plain SDK
client*: it uses only `engineroom` and dials the platform's public bot WS endpoint,
authenticating with a real ``crbk_`` key — no server imports, honouring ADR-0021.
The server references this file only by path; it never imports it.

Config comes from the environment the supervisor sets:
- ``ENGINEROOM_KEY`` — the house bot's ``crbk_`` API key (read by the SDK);
- ``ENGINEROOM_URL`` — the WS URL to dial back into (read by the SDK).

The move engine + time control come from argv (``--engine``/``--depth``/``--base``/
``--inc``) so the supervisor can pin each persona without leaking the key onto the
command line.

Resilience / self-connect timing: the SDK already reconnect-resumes a dropped game
(PROTOCOL §8). On top of that this runner wraps ``run(loop=True)`` in an outer
retry-with-backoff so an *initial* connection to a server that isn't accepting yet
(the self-connect race, ADR-0025 #3) just retries until it's up, and any hard
failure of the run loop restarts the whole client rather than exiting the process.

Run standalone (dev):

    ENGINEROOM_KEY=crbk_... ENGINEROOM_URL=ws://127.0.0.1:8001/api/bot/v1 \
      python sdk/house_bots/runner.py --engine minimax --depth 3 --base 180 --inc 0
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path


def _ensure_sdk_importable() -> None:
    """Make ``import engineroom`` work whether the SDK is installed (prod image:
    ``pip install engineroom``) or only present as the monorepo sibling source
    (dev/CI). Prefer an installed package; fall back to ``sdk/engineroom/src`` (or
    ``ER_ENGINEROOM_SRC`` if set)."""
    try:
        import engineroom  # noqa: F401
        return
    except ImportError:
        pass
    src = os.environ.get("ER_ENGINEROOM_SRC")
    if not src:
        src = str(Path(__file__).resolve().parent.parent / "engineroom" / "src")
    sys.path.insert(0, src)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Out-of-process house-bot SDK client.")
    p.add_argument("--engine", choices=["minimax", "random"], default="minimax")
    p.add_argument("--depth", type=int, default=3, help="minimax search depth")
    p.add_argument("--base", type=int, default=180, help="base clock seconds")
    p.add_argument("--inc", type=int, default=0, help="increment seconds")
    p.add_argument(
        "--connect-retry-backoff",
        type=float,
        default=1.0,
        dest="backoff",
        help="initial seconds to wait before retrying a failed connect/run",
    )
    p.add_argument(
        "--max-backoff",
        type=float,
        default=30.0,
        dest="max_backoff",
        help="cap for the exponential retry backoff",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s house-bot %(levelname)s %(message)s"
    )
    _ensure_sdk_importable()

    from engineroom import MinimaxBot, RandomBot

    args = _parse_args(argv)
    tc = (args.base, args.inc)

    def make_bot():
        if args.engine == "random":
            return RandomBot(time_control=tc)
        return MinimaxBot(depth=args.depth, time_control=tc)

    backoff = args.backoff
    while True:
        try:
            # loop=True keeps seeking new games forever; it only returns/raises on
            # a hard failure (e.g. the server not up yet, or a non-recoverable
            # protocol/transport error the SDK didn't already reconnect through).
            make_bot().run(loop=True)
            backoff = args.backoff  # a clean return → reset before retrying
        except KeyboardInterrupt:  # pragma: no cover - signal path
            return
        except Exception as exc:  # noqa: BLE001 - a supervisor runner must not die
            logging.warning(
                "run loop ended (%s); reconnecting in %.1fs", exc, backoff
            )
        time.sleep(backoff)
        backoff = min(backoff * 2, args.max_backoff)


if __name__ == "__main__":
    main()
