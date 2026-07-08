"""Per-bot API key generation + hashing (ADR-0014, D-k).

Format: `crbk_<43 base62 chars>` — a prefixed (greppable in leak scanning),
high-entropy (~256-bit) token. Stored only as `key_hash = HMAC-SHA256(pepper, token)`
(D-k): deterministic, so the WS handshake looks a key up in O(1); DB-leak-safe,
because forging a valid hash also requires the server-side pepper. The plaintext
is shown once and never persisted.

A 256-bit random token has no dictionary to attack, so a fast keyed hash is
appropriate here (unlike a human password, which needs a slow salted hash).
"""

import hashlib
import hmac
import secrets
import string

from ..config import settings

KEY_PREFIX = "crbk_"  # chess-room bot key
_SECRET_LEN = 43  # 43 * log2(62) ≈ 256 bits
_ALPHABET = string.ascii_letters + string.digits  # base62
_DISPLAY_PREFIX_LEN = len(KEY_PREFIX) + 8  # "crbk_" + first 8 secret chars


def _pepper() -> bytes:
    return settings.api_key_pepper.encode()


def hash_key(plaintext: str) -> str:
    """Deterministic keyed hash used both to store and to look up a key."""
    return hmac.new(_pepper(), plaintext.encode(), hashlib.sha256).hexdigest()


def verify_key(plaintext: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_key(plaintext), key_hash)


def generate_key() -> tuple[str, str, str]:
    """Return `(plaintext, key_hash, key_prefix)` for a fresh key.

    `plaintext` is returned to the caller exactly once; only `key_hash` and the
    non-secret `key_prefix` (for display/identification) are persisted.
    """
    secret = "".join(secrets.choice(_ALPHABET) for _ in range(_SECRET_LEN))
    plaintext = f"{KEY_PREFIX}{secret}"
    return plaintext, hash_key(plaintext), plaintext[:_DISPLAY_PREFIX_LEN]
