"""Integration tests for the SQL layer. Needs a scratch Postgres database:

    TEST_DATABASE_URL=postgresql://user:pass@localhost/football_test pytest
"""
import os

import pytest
from sqlalchemy import create_engine, text

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def conn():
    from etl.load import load
    counts = load(DB_URL, seed=11)
    assert counts["matches"] == 34
    engine = create_engine(DB_URL)
    with engine.connect() as c:
        yield c


def scalar(conn, sql):
    return conn.execute(text(sql)).scalar()


def test_team_totals_match_player_rows(conn):
    team = scalar(conn, "select sum(team_distance_km) from football.v_team_match")
    players = scalar(conn, "select sum(total_distance_m) / 1000.0 from football.v_player_match")
    assert float(team) == pytest.approx(float(players), abs=0.5)


def test_per90_normalisation(conn):
    row = conn.execute(text(
        "select total_distance_m, minutes, distance_per90_m from football.v_player_match "
        "where minutes between 20 and 40 limit 1")).one()
    assert row.distance_per90_m == round(row.total_distance_m * 90 / row.minutes)


def test_acwr_matches_manual_calculation(conn):
    row = conn.execute(text(
        "select player_id, load_date, acwr from football.v_player_acwr "
        "where acwr is not null order by load_date desc limit 1")).one()
    acute = scalar(conn, f"""select coalesce(sum(player_load), 0) from football.sessions
        where player_id = {row.player_id} and session_date > date '{row.load_date}' - 7
        and session_date <= date '{row.load_date}'""")
    chronic = scalar(conn, f"""select coalesce(sum(player_load), 0) / 4.0 from football.sessions
        where player_id = {row.player_id} and session_date > date '{row.load_date}' - 28
        and session_date <= date '{row.load_date}'""")
    assert float(row.acwr) == pytest.approx(float(acute) / float(chronic), abs=0.01)


def test_one_latest_day_row_per_player(conn):
    n = scalar(conn, "select count(*) from football.v_player_acwr where is_latest_day")
    assert n == scalar(conn, "select count(*) from football.players")


def test_acwr_starts_on_a_full_week(conn):
    first = scalar(conn, "select min(load_date) from football.v_player_acwr")
    assert first.isoweekday() == 1
