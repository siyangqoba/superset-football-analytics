"""Generate a season and load it into Postgres, then build the analytics views.

    python -m etl.load --database-url postgresql://analytics:analytics@localhost:5433/football
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from etl.generate import generate_season

log = logging.getLogger("etl")
SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
SCHEMA = "football"


def wait_for_db(engine: Engine, attempts: int = 30) -> None:
    for i in range(attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1"))
            return
        except OperationalError:
            log.info("waiting for database (%s/%s)", i + 1, attempts)
            time.sleep(2)
    raise RuntimeError("database not reachable")


def run_sql_file(engine: Engine, path: Path) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(path.read_text())


def load(database_url: str, seed: int = 42) -> dict[str, int]:
    engine = create_engine(database_url)
    wait_for_db(engine)
    run_sql_file(engine, SQL_DIR / "schema.sql")

    season = generate_season(seed=seed)
    counts = {}
    with engine.begin() as conn:
        for table in ("teams", "players", "matches", "sessions", "match_segments"):
            df = getattr(season, table)
            df.to_sql(table, conn, schema=SCHEMA, if_exists="append", index=False, method="multi",
                      chunksize=2000)
            counts[table] = len(df)
            log.info("loaded %-15s %6d rows", table, len(df))

    run_sql_file(engine, SQL_DIR / "views.sql")
    log.info("analytics views created")
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("ANALYTICS_DATABASE_URL"))
    parser.add_argument("--seed", type=int, default=int(os.environ.get("SEED", "42")))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or ANALYTICS_DATABASE_URL is required")
    load(args.database_url, args.seed)


if __name__ == "__main__":
    main()
