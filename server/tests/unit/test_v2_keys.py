"""Sub-step 4: API-key generation/hashing pure-function tests (no infra)."""

from engine_room.bots.keys import KEY_PREFIX, generate_key, hash_key, verify_key


def test_generate_key_shape():
    plaintext, key_hash, key_prefix = generate_key()
    assert plaintext.startswith(KEY_PREFIX)
    assert len(plaintext) == len(KEY_PREFIX) + 43  # ~256 bits of base62
    assert key_prefix == plaintext[: len(KEY_PREFIX) + 8]
    assert key_hash == hash_key(plaintext)
    # The stored hash is not the plaintext (never stored in the clear).
    assert plaintext not in key_hash


def test_hash_is_deterministic_and_verifies():
    plaintext, key_hash, _ = generate_key()
    assert hash_key(plaintext) == key_hash  # deterministic → O(1) lookup
    assert verify_key(plaintext, key_hash) is True
    assert verify_key(plaintext + "x", key_hash) is False


def test_keys_are_distinct():
    keys = {generate_key()[0] for _ in range(100)}
    assert len(keys) == 100
