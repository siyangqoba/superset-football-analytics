# Superset Football Analytics

An end-to-end sports-science analytics stack: a Python ETL that produces a season of GPS and heart-rate tracking data, a Postgres analytics layer, and an **Apache Superset** dashboard that is built entirely through code.

Coaches and performance staff can see how hard the team runs, which positions do what, where players tire during a match, and which players are carrying an injury-risky workload.

![Match performance tab](docs/match-performance.jpg)

## What's inside

```
etl/generate.py        season simulator: squad, fixtures, line-ups, subs, injuries, match + training sessions
etl/load.py            loads Postgres (idempotent) and builds the analytics views
sql/schema.sql         raw tables with keys and check constraints
sql/views.sql          analytics layer: per-90 metrics, team totals, zero-filled daily load, ACWR, fatigue splits
superset/bootstrap_dashboard.py
                       creates the DB connection, datasets, 14 charts, a 3-tab dashboard and native filters through Superset's REST API
docker-compose.yml     Postgres + ETL + Superset + bootstrap: one command to a working dashboard
tests/                 generator, SQL-view and dashboard-layout tests (pytest), run in GitHub Actions
```

### The data

Clubs only track their own players, so the data covers one squad (*Riverside United*, 25 players) across a 34-match double round-robin season plus a realistic training week between games (MD+1 recovery, MD-4/-3 loading, MD-1 activation). The generator models:

- **Position profiles** based on published match-running research: centre midfielders cover about 11 km per 90, wingers do the most sprinting, and goalkeepers about 5.5 km.
- Player **fitness**, opponent **intensity**, **rotation**, three **substitutions** per match (subs run harder per minute) and an **in-game fatigue** drop across 15-minute blocks.
- **Injuries** that remove players from matches and training for 10–35 days.

Everything is seeded and deterministic (`SEED=42`), so the dashboard is reproducible.

### The analytics layer (SQL)

| View | Purpose |
|---|---|
| `v_player_match` | One row per player per match, with distance / HSR / sprint **per 90**, metres per minute and HR as a % of max |
| `v_team_match` | Team totals per match alongside the result |
| `v_player_daily_load` | A calendar × player grid built with `generate_series`, zero-filled so rest days count toward the load windows |
| `v_player_acwr` | **Acute:Chronic Workload Ratio**: a 7-day rolling sum divided by a 28-day rolling weekly average, using window functions, plus a risk band (Optimal 0.8–1.3, Caution, High risk >1.5, Under-loaded) |
| `v_match_segments` | Distance per 15-minute block for the fatigue curve |

### The dashboard

| Tab | Charts |
|---|---|
| **Match Performance** | Season points, win rate, average team distance and HSR · running per match over the season · results donut · physical profile by position · running vs result · fatigue curve · top speed vs sprint volume bubble chart |
| **Players** | Leaderboard: appearances, minutes, per-90 running, top speed and HR load |
| **Load & Injury Risk** | Weekly ACWR heatmap (injury layoffs show as under-loaded blocks followed by return-to-play spikes) · current load status per player · squad weekly training load |

There are native **Position** and **Player** filters, and cross-filtering is enabled.

![Load and injury risk tab](docs/load-injury-risk.jpg)

## Run it

```bash
cp .env.example .env          # optional: set your own secret key / password
docker compose up --build
```

Then open **http://localhost:8088/superset/dashboard/football-performance/** and log in with `admin` / `admin`.

The `etl` and `bootstrap` containers run once and exit. Re-running `docker compose up bootstrap` rebuilds the dashboard in place.

### Without Docker

```bash
pip install -r requirements.txt
python -m etl.load --database-url postgresql://user:pass@localhost/football
python superset/bootstrap_dashboard.py --superset-url http://localhost:8088 \
    --username admin --password admin \
    --analytics-uri postgresql://user:pass@db-host:5432/football
```

`--analytics-uri` is the address *Superset* uses to reach Postgres, which can differ from the one your machine uses.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                    # generator + dashboard layout tests
TEST_DATABASE_URL=postgresql://... pytest # also runs the SQL view tests against a scratch DB
```

The SQL tests check the numbers independently: team totals equal the sum of player rows, the per-90 maths is correct, and ACWR is recomputed by hand from the raw sessions and compared with the view.

![Players tab](docs/players.jpg)

## Tech

Python 3.11 · pandas · NumPy · SQLAlchemy 2 · PostgreSQL 16 (window functions, `generate_series`) · Apache Superset 4.1 (ECharts, REST API, native filters) · Docker Compose · pytest · GitHub Actions
