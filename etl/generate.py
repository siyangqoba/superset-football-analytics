"""Simulate one season of GPS / heart-rate tracking data for a football club.

Clubs only track their own players, so the data covers a single squad across
league matches and training sessions. Values are drawn from position-specific
profiles taken from published match-running studies (e.g. ~10-11 km total
distance per 90 for midfielders, 25.2 km/h sprint threshold), then adjusted for
player fitness, opponent intensity, minutes played and in-match fatigue.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

CLUB = "Riverside United"
OPPONENTS = [
    "Harbour City", "Northgate Rovers", "Eastfield Athletic", "Kingsbridge FC",
    "Lakeside Wanderers", "Ironworks Town", "Meadow Park", "Coastal Rangers",
    "Highveld Stars", "Summit Albion", "Valley Celtic", "Westport County",
    "Granite Rock", "Bayview Dynamos", "Oldmill Town", "Sunridge United",
    "Clifton Phoenix",
]

# metres per 90 / max speed km/h / accelerations per 90, by position
POSITION_PROFILES = {
    "GK": dict(distance=5600, hsr=180, sprint=25, top_speed=25.5, accels=18, load=420),
    "CB": dict(distance=9900, hsr=520, sprint=150, top_speed=31.0, accels=42, load=880),
    "FB": dict(distance=10600, hsr=920, sprint=330, top_speed=33.0, accels=58, load=980),
    "CM": dict(distance=11300, hsr=780, sprint=190, top_speed=30.5, accels=55, load=1050),
    "W":  dict(distance=10800, hsr=1050, sprint=380, top_speed=33.8, accels=62, load=1010),
    "ST": dict(distance=10100, hsr=850, sprint=310, top_speed=33.2, accels=52, load=940),
}
SQUAD_SHAPE = {"GK": 3, "CB": 4, "FB": 4, "CM": 6, "W": 4, "ST": 4}
STARTING_XI = {"GK": 1, "CB": 2, "FB": 2, "CM": 3, "W": 2, "ST": 1}
SEGMENTS = ["0-15", "15-30", "30-45", "45-60", "60-75", "75-90"]
# share of distance covered per 15 min block, showing the typical second-half drop
SEGMENT_WEIGHTS = np.array([0.178, 0.170, 0.168, 0.168, 0.160, 0.156])

FIRST_NAMES = ["Sipho", "Thabo", "Lwazi", "Kagiso", "Mandla", "Tebogo", "Junior", "Neo",
               "Bongani", "Sifiso", "Themba", "Luca", "Mateo", "Kwame", "Ayo", "Tariq",
               "Daniel", "Ruben", "Yusuf", "Kyle", "Ethan", "Zola", "Lebo", "Andile", "Mpho"]
LAST_NAMES = ["Dlamini", "Nkosi", "Mokoena", "Khumalo", "Mahlangu", "Sithole", "van Wyk",
              "Botha", "Ndlovu", "Mthembu", "Pillay", "Naidoo", "Adams", "Petersen",
              "Fernandes", "Mensah", "Okafor", "Silva", "Hassan", "Smith", "Zulu",
              "Mabaso", "Cele", "Radebe", "Molefe"]


@dataclass
class Season:
    teams: pd.DataFrame
    players: pd.DataFrame
    matches: pd.DataFrame
    sessions: pd.DataFrame
    match_segments: pd.DataFrame


def _make_players(rng: random.Random) -> pd.DataFrame:
    rows, number = [], 1
    names = list(zip(rng.sample(FIRST_NAMES, 25), rng.sample(LAST_NAMES, 25), strict=True))
    for position, count in SQUAD_SHAPE.items():
        for _ in range(count):
            first, last = names.pop()
            age = rng.randint(19, 33)
            rows.append(
                dict(
                    player_id=number,
                    team_id=1,
                    player_name=f"{first} {last}",
                    position=position,
                    squad_number=number,
                    birth_date=date(2025 - age, rng.randint(1, 12), rng.randint(1, 28)),
                    max_hr=int(220 - age + rng.randint(-6, 6)),
                    fitness=round(rng.uniform(0.92, 1.08), 3),
                    quality=round(rng.uniform(0.0, 1.0), 3),
                )
            )
            number += 1
    return pd.DataFrame(rows)


def _injury_calendar(rng, players, season_start, season_end):
    """Return {player_id: set(dates unavailable)} with a handful of injuries."""
    out = {pid: set() for pid in players.player_id}
    days = (season_end - season_start).days
    for pid in rng.sample(list(players.player_id), 7):
        start = season_start + timedelta(days=rng.randint(20, days - 30))
        for d in range(rng.randint(10, 35)):
            out[pid].add(start + timedelta(days=d))
    return out


def generate_season(seed: int = 42, season: str = "2025/26",
                    start: date = date(2025, 8, 9)) -> Season:
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    teams = pd.DataFrame(
        [dict(team_id=1, team_name=CLUB, is_tracked=True)]
        + [dict(team_id=i + 2, team_name=n, is_tracked=False) for i, n in enumerate(OPPONENTS)]
    )
    players = _make_players(rng)

    # 34 matchdays: every opponent home and away, one game per weekend
    fixtures = [(o, True) for o in teams.team_id[1:]] + [(o, False) for o in teams.team_id[1:]]
    rng.shuffle(fixtures)
    match_dates = [start + timedelta(weeks=i) for i in range(len(fixtures))]
    season_end = match_dates[-1]
    injuries = _injury_calendar(rng, players, start, season_end)

    matches, sessions, segments = [], [], []
    session_id = 1
    for md, ((opp, home), match_date) in enumerate(zip(fixtures, match_dates, strict=True), start=1):
        match_id = md
        intensity = np_rng.normal(1.0, 0.04)  # some opponents make you run more

        available = players[[match_date not in injuries[p] for p in players.player_id]]
        lineup, bench = [], []
        for position, n in STARTING_XI.items():
            pool = available[available.position == position].sort_values("quality", ascending=False)
            # rotate: occasionally rest the best player
            chosen = pool.head(n + 1).sample(n=min(n, len(pool)), random_state=seed + md) \
                if rng.random() < 0.25 else pool.head(n)
            lineup += list(chosen.player_id)
            bench += [p for p in pool.player_id if p not in chosen.player_id.values]

        subs_off = rng.sample([p for p in lineup if players.loc[p - 1, "position"] != "GK"], 3)
        subs_on = rng.sample([p for p in bench if players.loc[p - 1, "position"] != "GK"],
                             min(3, len([p for p in bench if players.loc[p - 1, "position"] != "GK"])))
        minutes = {p: 90 for p in lineup}
        for off, on in zip(subs_off, subs_on, strict=False):
            m = rng.randint(55, 85)
            minutes[off] = m
            minutes[on] = 90 - m

        team_strength = players.set_index("player_id").loc[lineup, "quality"].mean()
        goals_for = int(np_rng.poisson(1.1 + team_strength * 0.9 + (0.25 if home else 0)))
        goals_against = int(np_rng.poisson(1.3 - team_strength * 0.4 + (0 if home else 0.2)))
        matches.append(
            dict(
                match_id=match_id, season=season, matchday=md, match_date=match_date,
                opponent_id=opp, venue="Home" if home else "Away",
                goals_for=goals_for, goals_against=goals_against,
                result="W" if goals_for > goals_against else "D" if goals_for == goals_against else "L",
            )
        )

        for pid, mins in minutes.items():
            p = players.loc[pid - 1]
            prof = POSITION_PROFILES[p.position]
            share = mins / 90
            # subs run harder per minute than starters
            per_min_boost = 1.08 if mins < 40 else 1.0
            f = p.fitness * intensity * per_min_boost
            dist = prof["distance"] * share * f * np_rng.normal(1, 0.05)
            hsr = prof["hsr"] * share * f * np_rng.normal(1, 0.12)
            sprint = min(hsr * 0.6, prof["sprint"] * share * f * np_rng.normal(1, 0.18))
            top = prof["top_speed"] * np.clip(np_rng.normal(1, 0.03), 0.9, 1.08) * (0.97 if mins < 30 else 1)
            avg_hr = int(p.max_hr * np.clip(np_rng.normal(0.84 if p.position != "GK" else 0.70, 0.02), 0.6, 0.93))
            sessions.append(
                dict(
                    session_id=session_id, player_id=pid, session_date=match_date,
                    session_type="Match", match_id=match_id, minutes=mins,
                    total_distance_m=round(dist), hsr_distance_m=round(hsr),
                    sprint_distance_m=round(max(sprint, 0)), top_speed_kmh=round(top, 2),
                    accelerations=int(prof["accels"] * share * f * np_rng.normal(1, 0.1)),
                    decelerations=int(prof["accels"] * 0.9 * share * f * np_rng.normal(1, 0.1)),
                    avg_hr=avg_hr, max_hr=int(min(p.max_hr, avg_hr + np_rng.integers(14, 24))),
                    player_load=round(prof["load"] * share * f * np_rng.normal(1, 0.06), 1),
                )
            )
            # 15-minute splits for players who started (fatigue curve)
            if pid in lineup:
                weights = SEGMENT_WEIGHTS * np_rng.normal(1, 0.03, 6) / (1.02 if p.fitness > 1 else 1)
                weights = weights / weights.sum()
                for i, seg in enumerate(SEGMENTS):
                    if (i + 1) * 15 > mins + 14:
                        break
                    # players subbed off: scale to their per-minute rate so blocks stay comparable
                    full_match_dist = dist * 90 / mins
                    segments.append(
                        dict(match_id=match_id, player_id=pid, segment=seg, segment_index=i + 1,
                             distance_m=round(full_match_dist * weights[i]),
                             hsr_distance_m=round(hsr * weights[i] * (1.15 - 0.06 * i) / 0.94))
                    )
            session_id += 1

        # training week leading into the next match: MD+1 recovery, MD-4, MD-3, MD-2, MD-1
        if md < len(fixtures):
            for offset, load_factor, kind in [(1, 0.25, "Recovery"), (3, 0.75, "Training"),
                                              (4, 0.9, "Training"), (5, 0.6, "Training"),
                                              (6, 0.35, "Activation")]:
                day = match_date + timedelta(days=offset)
                for p in players.itertuples():
                    if day in injuries[p.player_id]:
                        continue
                    prof = POSITION_PROFILES[p.position]
                    f = p.fitness * load_factor * np_rng.normal(1, 0.08)
                    sessions.append(
                        dict(
                            session_id=session_id, player_id=p.player_id, session_date=day,
                            session_type=kind, match_id=None,
                            minutes=int(np.clip(90 * (0.5 + load_factor / 2), 45, 95)),
                            total_distance_m=round(prof["distance"] * 0.65 * f),
                            hsr_distance_m=round(prof["hsr"] * 0.5 * f),
                            sprint_distance_m=round(prof["sprint"] * 0.35 * f),
                            top_speed_kmh=round(prof["top_speed"] * (0.82 + 0.1 * load_factor), 2),
                            accelerations=int(prof["accels"] * 0.7 * f),
                            decelerations=int(prof["accels"] * 0.65 * f),
                            avg_hr=int(p.max_hr * (0.62 + 0.15 * load_factor)),
                            max_hr=int(p.max_hr * (0.80 + 0.12 * load_factor)),
                            player_load=round(prof["load"] * 0.7 * f, 1),
                        )
                    )
                    session_id += 1

    players = players.drop(columns=["fitness", "quality"])
    return Season(
        teams=teams,
        players=players,
        matches=pd.DataFrame(matches),
        sessions=pd.DataFrame(sessions).astype({"match_id": "Int64"}),
        match_segments=pd.DataFrame(segments),
    )
