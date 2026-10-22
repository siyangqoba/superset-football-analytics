import pandas as pd
import pytest

from etl.generate import POSITION_PROFILES, STARTING_XI, generate_season


@pytest.fixture(scope="module")
def season():
    return generate_season(seed=7)


def test_is_deterministic():
    a, b = generate_season(seed=3), generate_season(seed=3)
    pd.testing.assert_frame_equal(a.sessions, b.sessions)
    pd.testing.assert_frame_equal(a.matches, b.matches)


def test_double_round_robin(season):
    assert len(season.matches) == 34
    counts = season.matches.groupby(["opponent_id", "venue"]).size()
    assert (counts == 1).all() and len(counts) == 34
    assert season.matches.match_date.is_monotonic_increasing


def test_every_match_uses_990_player_minutes(season):
    match_sessions = season.sessions[season.sessions.session_type == "Match"]
    per_match = match_sessions.groupby("match_id")
    assert (per_match.minutes.sum() == 11 * 90).all()
    assert (per_match.size() == 14).all()  # starting XI + 3 subs


def test_starting_xi_shape(season):
    starters = season.match_segments[season.match_segments.segment_index == 1]
    merged = starters.merge(season.players, on="player_id")
    shape = merged.groupby(["match_id", "position"]).size().unstack(fill_value=0)
    for position, n in STARTING_XI.items():
        assert (shape[position] == n).all(), position


def test_running_metrics_are_consistent(season):
    s = season.sessions
    assert (s.sprint_distance_m <= s.hsr_distance_m).all()
    assert (s.hsr_distance_m < s.total_distance_m).all()
    assert (s.avg_hr < s.max_hr).all()
    assert s.top_speed_kmh.between(15, 40).all()


def test_position_profiles_are_realistic(season):
    matches = season.sessions[(season.sessions.session_type == "Match") & (season.sessions.minutes == 90)]
    merged = matches.merge(season.players, on="player_id")
    per_pos = merged.groupby("position").total_distance_m.mean()
    for position, profile in POSITION_PROFILES.items():
        assert per_pos[position] == pytest.approx(profile["distance"], rel=0.08), position
    assert per_pos["GK"] < per_pos["CB"] < per_pos["CM"]


def test_injured_players_do_not_play_or_train(season):
    # every player should have gaps; at least some players miss a run of 10+ days
    s = season.sessions.sort_values("session_date")
    gaps = s.groupby("player_id").session_date.apply(lambda d: d.diff().max().days)
    assert (gaps >= 10).sum() >= 5


def test_fatigue_curve_declines(season):
    seg = season.match_segments.merge(season.players, on="player_id")
    seg = seg[seg.position != "GK"]
    avg = seg.groupby("segment_index").distance_m.mean()
    assert avg[1] > avg[3] > avg[6]
