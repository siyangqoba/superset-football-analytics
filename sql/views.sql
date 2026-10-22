-- Analytics layer used by the Superset datasets.

-- One row per player per match, with per-90 normalisation.
CREATE OR REPLACE VIEW football.v_player_match AS
SELECT
    s.session_id,
    m.match_id,
    m.season,
    m.matchday,
    m.match_date,
    o.team_name                                        AS opponent,
    m.venue,
    m.result,
    m.goals_for,
    m.goals_against,
    p.player_id,
    p.player_name,
    p.position,
    CASE p.position
        WHEN 'GK' THEN 'Goalkeeper' WHEN 'CB' THEN 'Centre Back'
        WHEN 'FB' THEN 'Full Back'  WHEN 'CM' THEN 'Central Midfield'
        WHEN 'W'  THEN 'Winger'     ELSE 'Striker'
    END                                                 AS position_name,
    s.minutes,
    (s.minutes >= 60)                                   AS is_starter_load,
    s.total_distance_m,
    s.hsr_distance_m,
    s.sprint_distance_m,
    s.top_speed_kmh,
    s.accelerations,
    s.decelerations,
    s.avg_hr,
    s.max_hr,
    round(100.0 * s.avg_hr / p.max_hr, 1)               AS avg_hr_pct_max,
    s.player_load,
    round(s.total_distance_m  * 90.0 / NULLIF(s.minutes, 0)) AS distance_per90_m,
    round(s.hsr_distance_m    * 90.0 / NULLIF(s.minutes, 0)) AS hsr_per90_m,
    round(s.sprint_distance_m * 90.0 / NULLIF(s.minutes, 0)) AS sprint_per90_m,
    round(s.total_distance_m::numeric / NULLIF(s.minutes, 0), 1) AS metres_per_minute
FROM football.sessions s
JOIN football.matches  m ON m.match_id = s.match_id
JOIN football.players  p ON p.player_id = s.player_id
JOIN football.teams    o ON o.team_id = m.opponent_id
WHERE s.session_type = 'Match';

-- Team totals per match.
CREATE OR REPLACE VIEW football.v_team_match AS
SELECT
    match_id, season, matchday, match_date, opponent, venue, result, goals_for, goals_against,
    round(sum(total_distance_m) / 1000.0, 2)  AS team_distance_km,
    round(sum(hsr_distance_m) / 1000.0, 2)    AS team_hsr_km,
    round(sum(sprint_distance_m) / 1000.0, 2) AS team_sprint_km,
    max(top_speed_kmh)                        AS fastest_kmh,
    sum(accelerations)                        AS team_accelerations,
    count(*)                                  AS players_used
FROM football.v_player_match
GROUP BY match_id, season, matchday, match_date, opponent, venue, result, goals_for, goals_against;

-- Daily load per player (zero-filled), then acute:chronic workload ratio.
-- Acute = 7-day total, chronic = 28-day rolling weekly average.
-- ACWR between 0.8 and 1.3 is the commonly cited "sweet spot"; above 1.5 is high risk.
CREATE OR REPLACE VIEW football.v_player_daily_load AS
WITH bounds AS (
    SELECT min(session_date) AS d0, max(session_date) AS d1 FROM football.sessions
), calendar AS (
    SELECT p.player_id, p.player_name, p.position, d::date AS load_date
    FROM football.players p
    CROSS JOIN bounds
    CROSS JOIN generate_series(bounds.d0, bounds.d1, interval '1 day') AS d
), daily AS (
    SELECT player_id, session_date, sum(player_load) AS load, sum(total_distance_m) AS distance_m
    FROM football.sessions GROUP BY player_id, session_date
)
SELECT
    c.player_id, c.player_name, c.position, c.load_date,
    COALESCE(d.load, 0)       AS daily_load,
    COALESCE(d.distance_m, 0) AS daily_distance_m,
    sum(COALESCE(d.load, 0)) OVER w7  AS acute_load,
    sum(COALESCE(d.load, 0)) OVER w28 / 4.0 AS chronic_load,
    count(*) OVER w28 AS days_in_window
FROM calendar c
LEFT JOIN daily d ON d.player_id = c.player_id AND d.session_date = c.load_date
WINDOW
    w7  AS (PARTITION BY c.player_id ORDER BY c.load_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),
    w28 AS (PARTITION BY c.player_id ORDER BY c.load_date ROWS BETWEEN 27 PRECEDING AND CURRENT ROW);

CREATE OR REPLACE VIEW football.v_player_acwr AS
WITH complete AS (
    -- skip the first 4 weeks, where chronic load is still incomplete
    SELECT * FROM football.v_player_daily_load WHERE days_in_window = 28
), first_full_week AS (
    SELECT (date_trunc('week', min(load_date)) + interval '7 days')::date AS week0 FROM complete
)
SELECT
    c.player_id, c.player_name, c.position, c.load_date,
    date_trunc('week', c.load_date)::date AS week_start,
    c.daily_load, c.acute_load, round(c.chronic_load, 1) AS chronic_load,
    round(c.acute_load / NULLIF(c.chronic_load, 0), 2) AS acwr,
    CASE
        WHEN c.chronic_load = 0 THEN 'No data'
        WHEN c.acute_load / c.chronic_load > 1.5 THEN 'High risk'
        WHEN c.acute_load / c.chronic_load > 1.3 THEN 'Caution'
        WHEN c.acute_load / c.chronic_load < 0.8 THEN 'Under-loaded'
        ELSE 'Optimal'
    END AS risk_band,
    (c.load_date = max(c.load_date) OVER ()) AS is_latest_day
FROM complete c, first_full_week f
WHERE c.load_date >= f.week0;

-- Average distance by 15-minute block, for fatigue analysis.
CREATE OR REPLACE VIEW football.v_match_segments AS
SELECT
    ms.match_id, m.match_date, m.result, ms.segment, ms.segment_index,
    p.player_id, p.player_name, p.position,
    ms.distance_m, ms.hsr_distance_m
FROM football.match_segments ms
JOIN football.matches m ON m.match_id = ms.match_id
JOIN football.players p ON p.player_id = ms.player_id;
