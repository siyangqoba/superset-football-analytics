-- Raw tables. Recreated on every ETL run so the load is idempotent.
DROP SCHEMA IF EXISTS football CASCADE;
CREATE SCHEMA football;

CREATE TABLE football.teams (
    team_id     integer PRIMARY KEY,
    team_name   text    NOT NULL UNIQUE,
    is_tracked  boolean NOT NULL DEFAULT false
);

CREATE TABLE football.players (
    player_id    integer PRIMARY KEY,
    team_id      integer NOT NULL REFERENCES football.teams,
    player_name  text    NOT NULL,
    position     text    NOT NULL CHECK (position IN ('GK','CB','FB','CM','W','ST')),
    squad_number integer NOT NULL,
    birth_date   date    NOT NULL,
    max_hr       integer NOT NULL
);

CREATE TABLE football.matches (
    match_id      integer PRIMARY KEY,
    season        text    NOT NULL,
    matchday      integer NOT NULL,
    match_date    date    NOT NULL,
    opponent_id   integer NOT NULL REFERENCES football.teams,
    venue         text    NOT NULL CHECK (venue IN ('Home','Away')),
    goals_for     integer NOT NULL,
    goals_against integer NOT NULL,
    result        char(1) NOT NULL CHECK (result IN ('W','D','L'))
);

CREATE TABLE football.sessions (
    session_id        integer PRIMARY KEY,
    player_id         integer NOT NULL REFERENCES football.players,
    session_date      date    NOT NULL,
    session_type      text    NOT NULL,
    match_id          integer REFERENCES football.matches,
    minutes           integer NOT NULL,
    total_distance_m  integer NOT NULL,
    hsr_distance_m    integer NOT NULL,   -- high-speed running, > 19.8 km/h
    sprint_distance_m integer NOT NULL,   -- > 25.2 km/h
    top_speed_kmh     numeric(5,2) NOT NULL,
    accelerations     integer NOT NULL,   -- > 3 m/s²
    decelerations     integer NOT NULL,
    avg_hr            integer NOT NULL,
    max_hr            integer NOT NULL,
    player_load       numeric(8,1) NOT NULL
);
CREATE INDEX ON football.sessions (player_id, session_date);

CREATE TABLE football.match_segments (
    match_id       integer NOT NULL REFERENCES football.matches,
    player_id      integer NOT NULL REFERENCES football.players,
    segment        text    NOT NULL,
    segment_index  integer NOT NULL,
    distance_m     integer NOT NULL,
    hsr_distance_m integer NOT NULL,
    PRIMARY KEY (match_id, player_id, segment_index)
);
