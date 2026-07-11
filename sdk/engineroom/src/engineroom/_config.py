"""Config env-var resolution (KAN-71).

The SDK's config env vars were renamed ``CHESSROOM_*`` → ``ENGINEROOM_*`` to match
the ``engineroom`` package name. Resolution prefers the new names; the legacy
``CHESSROOM_*`` names still work but sourcing a value from one emits a **one-time**
``DeprecationWarning`` naming the new var (per legacy var, per process, so a looping
bot doesn't spam). Passing ``key=`` / ``url=`` to ``Bot`` skips the env entirely.

Kept as a tiny module (no server imports, ADR-0021) so both ``Bot`` and the
``engineroom-uci`` bridge resolve config identically.
"""

from __future__ import annotations

import os
import warnings
from typing import Optional

ENV_KEY = "ENGINEROOM_KEY"
ENV_KEY_LEGACY = "CHESSROOM_KEY"
ENV_URL = "ENGINEROOM_URL"
ENV_URL_LEGACY = "CHESSROOM_URL"

# One legacy-var → warned-once-per-process guard.
_warned: set[str] = set()


def _warn_once(new_name: str, legacy_name: str) -> None:
    if legacy_name in _warned:
        return
    _warned.add(legacy_name)
    warnings.warn(
        f"{legacy_name} is deprecated; set {new_name} instead "
        f"(the SDK's config vars were renamed to match the engineroom package).",
        DeprecationWarning,
        stacklevel=3,
    )


def _resolve(new_name: str, legacy_name: str) -> Optional[str]:
    """Return ``new_name``'s value if set (non-empty), else fall back to the legacy
    ``legacy_name`` (warned once). ``None`` when neither is set."""
    value = os.environ.get(new_name)
    if value:
        return value
    legacy = os.environ.get(legacy_name)
    if legacy:
        _warn_once(new_name, legacy_name)
        return legacy
    return None


def env_key() -> Optional[str]:
    """The API key from ``ENGINEROOM_KEY`` (else deprecated ``CHESSROOM_KEY``)."""
    return _resolve(ENV_KEY, ENV_KEY_LEGACY)


def env_url() -> Optional[str]:
    """The WS URL from ``ENGINEROOM_URL`` (else deprecated ``CHESSROOM_URL``)."""
    return _resolve(ENV_URL, ENV_URL_LEGACY)
