"""V5 sub-step 1 checkpoint: control messages parse, ELO settings load, and the
pure Elo math (ADR-0011 / 0016 E8) matches a hand-computed table."""

import pytest

from engine_room.config import Settings
from engine_room.game import ratings
from engine_room.protocol.messages import (
    DrawAccept,
    DrawOffer,
    ProtocolError,
    Resign,
    parse_client_message,
)

# --- protocol -----------------------------------------------------------------


def test_parse_resign():
    msg = parse_client_message('{"type":"resign","game_id":"game_1"}')
    assert isinstance(msg, Resign)
    assert msg.game_id == "game_1"


def test_parse_draw_offer():
    msg = parse_client_message('{"type":"draw_offer","game_id":"game_1"}')
    assert isinstance(msg, DrawOffer)


def test_parse_draw_accept():
    msg = parse_client_message('{"type":"draw_accept","game_id":"game_1"}')
    assert isinstance(msg, DrawAccept)


def test_control_requires_game_id():
    with pytest.raises(ProtocolError):
        parse_client_message('{"type":"resign"}')


# --- config -------------------------------------------------------------------


def test_elo_settings_defaults():
    s = Settings()
    assert s.elo_k_provisional == 32
    assert s.elo_k_default == 16
    assert s.elo_provisional_games == 30


def test_elo_settings_env_override(monkeypatch):
    monkeypatch.setenv("ER_ELO_K_DEFAULT", "24")
    monkeypatch.setenv("ER_ELO_PROVISIONAL_GAMES", "10")
    s = Settings()
    assert s.elo_k_default == 24
    assert s.elo_provisional_games == 10


# --- pure Elo math ------------------------------------------------------------


def test_expected_score_symmetry():
    # Equal ratings → 0.5 each; the two expected scores always sum to 1.
    assert ratings.expected_score(1200, 1200) == pytest.approx(0.5)
    combined = ratings.expected_score(1400, 1200) + ratings.expected_score(1200, 1400)
    assert combined == pytest.approx(1.0)


def test_expected_score_favors_higher_rating():
    assert ratings.expected_score(1600, 1200) > 0.5


def test_k_factor_provisional_then_default():
    assert ratings.k_factor(0) == 32
    assert ratings.k_factor(29) == 32
    assert ratings.k_factor(30) == 16
    assert ratings.k_factor(100) == 16


def test_k_factor_overrides():
    assert ratings.k_factor(5, provisional_k=40, provisional_games=3) == 16
    assert ratings.k_factor(2, provisional_k=40, provisional_games=3, default_k=20) == 40


def test_equal_win_moves_by_half_k():
    # 1200 vs 1200: expected 0.5, K=16 default → winner +8, loser -8.
    assert ratings.updated(1200, 1200, 1.0, 16) == 1208
    assert ratings.updated(1200, 1200, 0.0, 16) == 1192


def test_equal_draw_no_change():
    assert ratings.updated(1200, 1200, 0.5, 16) == 1200


def test_provisional_win_moves_more():
    assert ratings.updated(1200, 1200, 1.0, 32) == 1216


def test_upset_win_moves_more_than_expected_win():
    # Underdog beating a favorite gains more than a favorite beating an underdog.
    underdog_gain = ratings.updated(1200, 1600, 1.0, 16) - 1200
    favorite_gain = ratings.updated(1600, 1200, 1.0, 16) - 1600
    assert underdog_gain > favorite_gain


def test_scores_mapping():
    assert ratings.scores("white_wins") == (1.0, 0.0)
    assert ratings.scores("black_wins") == (0.0, 1.0)
    assert ratings.scores("draw") == (0.5, 0.5)
