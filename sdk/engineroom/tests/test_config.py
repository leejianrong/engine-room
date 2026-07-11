"""Env-var resolution matrix (KAN-71): ENGINEROOM_* is primary; CHESSROOM_* is an
accepted-but-deprecated fallback that warns once. Passing key=/url= skips the env.

No infra — pure config resolution over monkeypatched env, mirroring the fast,
infra-free test layer (ADR-0021).
"""

from __future__ import annotations

import warnings

import pytest

import engineroom
from engineroom import Bot, RandomBot, _config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start each test with all four vars unset and the one-time warn guard reset."""
    for name in ("ENGINEROOM_KEY", "CHESSROOM_KEY", "ENGINEROOM_URL", "CHESSROOM_URL"):
        monkeypatch.delenv(name, raising=False)
    _config._warned.clear()
    yield
    _config._warned.clear()


# ------------------------------------------------------------------ new-only
def test_new_key_used_without_warning(monkeypatch):
    monkeypatch.setenv("ENGINEROOM_KEY", "crbk_new")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert _config.env_key() == "crbk_new"
    assert caught == []
    assert Bot(connect=lambda: None).key == "crbk_new"


def test_new_url_used_without_warning(monkeypatch):
    monkeypatch.setenv("ENGINEROOM_URL", "ws://new/api/bot/v1")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert _config.env_url() == "ws://new/api/bot/v1"
    assert caught == []


# ------------------------------------------------------------------ old-only
def test_legacy_key_used_with_one_time_warning(monkeypatch):
    monkeypatch.setenv("CHESSROOM_KEY", "crbk_legacy")
    with pytest.warns(DeprecationWarning, match="ENGINEROOM_KEY"):
        assert _config.env_key() == "crbk_legacy"
    # One-time: a second read of the same legacy var is silent.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert _config.env_key() == "crbk_legacy"
    assert caught == []


def test_legacy_url_used_with_one_time_warning(monkeypatch):
    monkeypatch.setenv("CHESSROOM_URL", "ws://legacy/api/bot/v1")
    with pytest.warns(DeprecationWarning, match="ENGINEROOM_URL"):
        assert _config.env_url() == "ws://legacy/api/bot/v1"


# ------------------------------------------------------------------ both-set
def test_new_wins_when_both_set_without_warning(monkeypatch):
    monkeypatch.setenv("ENGINEROOM_KEY", "crbk_new")
    monkeypatch.setenv("CHESSROOM_KEY", "crbk_legacy")
    monkeypatch.setenv("ENGINEROOM_URL", "ws://new")
    monkeypatch.setenv("CHESSROOM_URL", "ws://legacy")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert _config.env_key() == "crbk_new"
        assert _config.env_url() == "ws://new"
    assert caught == []


# -------------------------------------------------------------------- neither
async def test_missing_key_raises_config_error():
    # Neither var set + no explicit key → the existing missing-key error.
    bot = RandomBot(connect=lambda: None)
    assert bot.key is None
    with pytest.raises(engineroom.ConfigError):
        await bot._run(loop=False)


def test_explicit_args_skip_env_and_do_not_warn(monkeypatch):
    # A legacy var is present but key=/url= are passed explicitly → no fallback,
    # no warning (the env is never consulted for those values).
    monkeypatch.setenv("CHESSROOM_KEY", "crbk_legacy")
    monkeypatch.setenv("CHESSROOM_URL", "ws://legacy")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bot = Bot(key="crbk_explicit", url="ws://explicit", connect=lambda: None)
    assert bot.key == "crbk_explicit"
    assert bot.url == "ws://explicit"
    assert caught == []
