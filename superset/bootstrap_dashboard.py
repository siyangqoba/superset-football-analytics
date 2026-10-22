"""Create the Football Performance dashboard in Superset through its REST API.

Idempotent: re-running replaces the dashboard and its charts, and reuses the
database connection and datasets if they already exist.

    python superset/bootstrap_dashboard.py \
        --superset-url http://localhost:8088 --username admin --password admin \
        --analytics-uri postgresql://analytics:analytics@analytics-db:5432/football
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Any

import requests

log = logging.getLogger("bootstrap")

DATABASE_NAME = "Football Analytics"
SCHEMA = "football"
DASHBOARD_SLUG = "football-performance"
DASHBOARD_TITLE = "Football Performance & Player Load"
DATASETS = ["v_team_match", "v_player_match", "v_match_segments", "v_player_acwr"]


# --------------------------------------------------------------------------- API client
class Superset:
    def __init__(self, base_url: str, username: str, password: str):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self._wait_until_healthy()
        token = self._post_raw(
            "/api/v1/security/login",
            {"username": username, "password": password, "provider": "db", "refresh": True},
        )["access_token"]
        self.s.headers["Authorization"] = f"Bearer {token}"
        csrf = self.get("/api/v1/security/csrf_token/")["result"]
        self.s.headers.update({"X-CSRFToken": csrf, "Referer": self.base})

    def _wait_until_healthy(self, attempts: int = 60) -> None:
        for i in range(attempts):
            try:
                if self.s.get(f"{self.base}/health", timeout=5).ok:
                    return
            except requests.ConnectionError:
                pass
            log.info("waiting for Superset (%s/%s)", i + 1, attempts)
            time.sleep(3)
        raise RuntimeError(f"Superset not reachable at {self.base}")

    def _post_raw(self, path: str, payload: dict) -> dict:
        r = self.s.post(f"{self.base}{path}", json=payload, timeout=60)
        if not r.ok:
            raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text}")
        return r.json()

    def get(self, path: str, **params) -> dict:
        r = self.s.get(f"{self.base}{path}", params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, payload: dict) -> dict:
        return self._post_raw(path, payload)

    def put(self, path: str, payload: dict) -> dict:
        r = self.s.put(f"{self.base}{path}", json=payload, timeout=60)
        if not r.ok:
            raise RuntimeError(f"PUT {path} -> {r.status_code}: {r.text}")
        return r.json()

    def delete(self, path: str) -> None:
        r = self.s.delete(f"{self.base}{path}", timeout=60)
        if r.status_code not in (200, 404):
            raise RuntimeError(f"DELETE {path} -> {r.status_code}: {r.text}")

    def find(self, resource: str, column: str, value: str) -> list[dict]:
        q = rison({"filters": [{"col": column, "opr": "eq", "value": value}], "page_size": 100})
        return self.get(f"/api/v1/{resource}/", q=q)["result"]


def rison(obj: Any) -> str:
    """Minimal Rison encoder (enough for Superset list filters)."""
    if isinstance(obj, bool):
        return "!t" if obj else "!f"
    if isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, str):
        return "'" + obj.replace("!", "!!").replace("'", "!'") + "'"
    if isinstance(obj, list):
        return "!(" + ",".join(rison(v) for v in obj) + ")"
    if isinstance(obj, dict):
        return "(" + ",".join(f"{k}:{rison(v)}" for k, v in obj.items()) + ")"
    raise TypeError(type(obj))


# --------------------------------------------------------------------------- chart helpers
def metric(sql: str, label: str) -> dict:
    return {"expressionType": "SQL", "sqlExpression": sql, "label": label, "optionName": label}


def sql_filter(sql: str) -> dict:
    return {"expressionType": "SQL", "sqlExpression": sql, "clause": "WHERE"}


def big_number(m: dict, subheader: str, fmt: str = ",.0f") -> dict:
    return {"viz_type": "big_number_total", "metric": m, "subheader": subheader,
            "y_axis_format": fmt, "header_font_size": 0.4, "subheader_font_size": 0.15}


def bar(x: str, metrics: list[dict], filters: list[dict] | None = None, fmt: str = ",.0f",
        sort_by_label: bool = True, **extra) -> dict:
    return {"viz_type": "echarts_timeseries_bar", "x_axis": x, "metrics": metrics, "groupby": [],
            "adhoc_filters": filters or [], "orientation": "vertical", "y_axis_format": fmt,
            "x_axis_sort": x if sort_by_label else None, "x_axis_sort_asc": True,
            "show_legend": len(metrics) > 1, "show_value": True, "rich_tooltip": True,
            "row_limit": 1000, "color_scheme": "supersetColors", **extra}


def line(x: str, metrics: list[dict], fmt: str = ",.1f", grain: str = "P1D", **extra) -> dict:
    return {"viz_type": "echarts_timeseries_line", "x_axis": x, "time_grain_sqla": grain,
            "metrics": metrics, "groupby": [], "adhoc_filters": [], "markerEnabled": True,
            "markerSize": 5, "rich_tooltip": True, "show_legend": True, "y_axis_format": fmt,
            "row_limit": 10000, "color_scheme": "supersetColors", "truncateXAxis": True, **extra}


# --------------------------------------------------------------------------- chart definitions
def chart_specs() -> dict[str, tuple[str, str, dict]]:
    """key -> (dataset, chart name, form data)."""
    points = metric("SUM(CASE result WHEN 'W' THEN 3 WHEN 'D' THEN 1 ELSE 0 END)", "Points")
    starters = [sql_filter("minutes >= 60")]
    return {
        "kpi_record": ("v_team_match", "Season Points",
                       big_number(points, "league points from 34 matches")),
        "kpi_winrate": ("v_team_match", "Win Rate",
                        big_number(metric("AVG(CASE WHEN result = 'W' THEN 1.0 ELSE 0 END)", "Win rate"),
                                   "of matches won", ".0%")),
        "kpi_distance": ("v_team_match", "Avg Team Distance",
                         big_number(metric("AVG(team_distance_km)", "km"), "km covered per match", ",.1f")),
        "kpi_hsr": ("v_team_match", "Avg Team High-Speed Running",
                    big_number(metric("AVG(team_hsr_km)", "km"), "km above 19.8 km/h per match", ",.2f")),
        "team_trend": ("v_team_match", "Team Running per Match",
                       line("match_date", [metric("SUM(team_distance_km)", "Total distance (km)"),
                                           metric("SUM(team_hsr_km) * 10", "HSR (km × 10)")])),
        "results": ("v_team_match", "Results",
                    {"viz_type": "pie", "groupby": ["result"], "metric": metric("COUNT(*)", "Matches"),
                     "adhoc_filters": [], "row_limit": 10, "donut": True, "show_labels": True,
                     "label_type": "key_value", "show_legend": True, "innerRadius": 45,
                     "outerRadius": 75, "color_scheme": "supersetColors", "sort_by_metric": True}),
        "running_by_result": ("v_team_match", "Running vs Result",
                              bar("result", [metric("AVG(team_distance_km)", "Distance (km)"),
                                             metric("AVG(team_hsr_km)", "HSR (km)")], fmt=",.1f")),
        "position_profile": ("v_player_match", "Physical Profile by Position (per 90)",
                             bar("position_name", [metric("AVG(hsr_per90_m)", "HSR / 90 (m)"),
                                                   metric("AVG(sprint_per90_m)", "Sprint / 90 (m)"),
                                                   metric("AVG(accelerations * 90.0 / minutes)", "Accels / 90")],
                                 filters=starters)),
        "fatigue": ("v_match_segments", "Fatigue Curve: Distance per 15 min",
                    bar("segment", [metric("AVG(distance_m)", "Avg distance (m)")],
                        filters=[sql_filter("position <> 'GK'")],
                        y_axis_bounds=[1400, None])),
        "speed_scatter": ("v_player_match", "Top Speed vs Sprint Volume",
                          {"viz_type": "bubble_v2", "entity": "player_name", "series": "position_name",
                           "x": metric("MAX(top_speed_kmh)", "Top speed (km/h)"),
                           "y": metric("AVG(sprint_per90_m)", "Sprint m / 90"),
                           "size": metric("SUM(minutes)", "Minutes"), "adhoc_filters": starters,
                           "max_bubble_size": "15", "row_limit": 100, "color_scheme": "supersetColors",
                           "show_legend": True, "x_axis_label": "Top speed (km/h)",
                           "y_axis_label": "Sprint distance per 90 (m)", "xAxisFormat": ",.1f",
                           "y_axis_format": ",.0f", "opacity": 0.7}),
        "leaderboard": ("v_player_match", "Player Leaderboard",
                        {"viz_type": "table", "query_mode": "aggregate",
                         "groupby": ["player_name", "position_name"],
                         "metrics": [metric("COUNT(*)", "Apps"),
                                     metric("SUM(minutes)", "Minutes"),
                                     metric("ROUND(SUM(total_distance_m) * 90.0 / SUM(minutes))", "Distance / 90 (m)"),
                                     metric("ROUND(SUM(hsr_distance_m) * 90.0 / SUM(minutes))", "HSR / 90 (m)"),
                                     metric("ROUND(SUM(sprint_distance_m) * 90.0 / SUM(minutes))", "Sprint / 90 (m)"),
                                     metric("MAX(top_speed_kmh)", "Top speed (km/h)"),
                                     metric("ROUND(AVG(avg_hr_pct_max), 1)", "Avg HR % max")],
                         "adhoc_filters": [], "orderby": [[metric("SUM(minutes)", "Minutes"), False]],
                         "order_desc": True, "row_limit": 100, "table_timestamp_format": "smart_date",
                         "show_cell_bars": True, "allow_rearrange_columns": True,
                         "conditional_formatting": [
                             {"colorScheme": "#ACE1C4", "column": "Top speed (km/h)", "operator": ">=",
                              "targetValue": 34},
                         ]}),
        "acwr_heatmap": ("v_player_acwr", "Weekly ACWR by Player",
                         {"viz_type": "heatmap_v2", "x_axis": "week_start", "time_grain_sqla": "P1W",
                          "groupby": "player_name", "metric": metric("ROUND(MAX(acwr), 2)", "Peak ACWR"),
                          "adhoc_filters": [], "row_limit": 10000, "linear_color_scheme": "superset_seq_1",
                          "normalize_across": "heatmap", "value_bounds": [0.6, 1.8], "show_legend": True,
                          "show_percentage": False, "show_values": False, "left_margin": "auto",
                          "bottom_margin": "auto", "xscale_interval": -1, "yscale_interval": -1,
                          "x_axis_time_format": "%d %b", "sort_x_axis": "alpha_asc",
                          "sort_y_axis": "alpha_asc", "y_axis_format": ".2f"}),
        "acwr_now": ("v_player_acwr", "Current Load Status",
                     {"viz_type": "table", "query_mode": "raw",
                      "all_columns": ["player_name", "position", "acute_load", "chronic_load", "acwr", "risk_band"],
                      "adhoc_filters": [sql_filter("is_latest_day")],
                      "order_by_cols": ['["acwr", false]'], "row_limit": 50, "server_page_length": 0,
                      "conditional_formatting": [
                          {"colorScheme": "#EFA1AA", "column": "acwr", "operator": ">", "targetValue": 1.5},
                          {"colorScheme": "#FDE380", "column": "acwr", "operator": "between",
                           "targetValueLeft": 1.3, "targetValueRight": 1.5},
                      ]}),
        "team_load": ("v_player_acwr", "Squad Weekly Training Load",
                      line("week_start", [metric("SUM(daily_load)", "Total player load")], fmt=",.0f",
                           grain="P1W", show_legend=False, markerEnabled=True)),
    }


# Tabs -> rows -> (chart key, width out of 12, height)
LAYOUT = [
    ("Match Performance", [
        [("kpi_record", 3, 28), ("kpi_winrate", 3, 28), ("kpi_distance", 3, 28), ("kpi_hsr", 3, 28)],
        [("team_trend", 8, 60), ("results", 4, 60)],
        [("position_profile", 8, 60), ("running_by_result", 4, 60)],
        [("fatigue", 6, 60), ("speed_scatter", 6, 60)],
    ]),
    ("Players", [
        [("leaderboard", 12, 90)],
    ]),
    ("Load & Injury Risk", [
        [("acwr_heatmap", 12, 100)],
        [("acwr_now", 6, 80), ("team_load", 6, 80)],
    ]),
]

INTRO_MARKDOWN = """### Riverside United · Season 2025/26
GPS and heart-rate tracking from **34 league matches** and every training session.
**HSR** = high-speed running above 19.8 km/h, **Sprint** = above 25.2 km/h.
**ACWR** (acute:chronic workload ratio) compares the last 7 days' load with the 28-day average:
0.8–1.3 is the target zone and above 1.5 means a higher injury risk."""


def build_position_json(chart_ids: dict[str, int], names: dict[str, str]) -> dict:
    pos: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": DASHBOARD_TITLE}},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-intro", "TABS-main"],
                    "parents": ["ROOT_ID"]},
        "ROW-intro": {"type": "ROW", "id": "ROW-intro", "children": ["MARKDOWN-intro"],
                      "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        "MARKDOWN-intro": {"type": "MARKDOWN", "id": "MARKDOWN-intro", "children": [],
                           "parents": ["ROOT_ID", "GRID_ID", "ROW-intro"],
                           "meta": {"width": 12, "height": 18, "code": INTRO_MARKDOWN}},
        "TABS-main": {"type": "TABS", "id": "TABS-main", "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                      "meta": {}},
    }
    for t, (tab_name, rows) in enumerate(LAYOUT):
        tab_id = f"TAB-{t}"
        tab_parents = ["ROOT_ID", "GRID_ID", "TABS-main"]
        pos["TABS-main"]["children"].append(tab_id)
        pos[tab_id] = {"type": "TAB", "id": tab_id, "children": [], "parents": tab_parents,
                       "meta": {"text": tab_name, "defaultText": tab_name}}
        for r, row in enumerate(rows):
            row_id = f"ROW-{t}-{r}"
            row_parents = tab_parents + [tab_id]
            pos[tab_id]["children"].append(row_id)
            pos[row_id] = {"type": "ROW", "id": row_id, "children": [], "parents": row_parents,
                           "meta": {"background": "BACKGROUND_TRANSPARENT"}}
            for key, width, height in row:
                cid = f"CHART-{key}"
                pos[row_id]["children"].append(cid)
                pos[cid] = {"type": "CHART", "id": cid, "children": [], "parents": row_parents + [row_id],
                            "meta": {"width": width, "height": height, "chartId": chart_ids[key],
                                     "sliceName": names[key], "uuid": None}}
    return pos


def native_filter(fid: str, name: str, dataset_id: int, column: str, excluded: list[int]) -> dict:
    return {
        "id": fid, "name": name, "type": "NATIVE_FILTER", "filterType": "filter_select",
        "targets": [{"datasetId": dataset_id, "column": {"name": column}}],
        "controlValues": {"enableEmptyFilter": False, "defaultToFirstItem": False, "multiSelect": True,
                          "searchAllOptions": False, "inverseSelection": False},
        "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
        "cascadeParentIds": [], "scope": {"rootPath": ["ROOT_ID"], "excluded": excluded},
        "description": "",
    }


# --------------------------------------------------------------------------- main flow
def ensure_database(api: Superset, uri: str) -> int:
    existing = api.find("database", "database_name", DATABASE_NAME)
    payload = {"database_name": DATABASE_NAME, "sqlalchemy_uri": uri, "expose_in_sqllab": True,
               "allow_run_async": False}
    if existing:
        db_id = existing[0]["id"]
        api.put(f"/api/v1/database/{db_id}", payload)
    else:
        db_id = api.post("/api/v1/database/", payload)["id"]
    log.info("database '%s' -> id %s", DATABASE_NAME, db_id)
    return db_id


def ensure_dataset(api: Superset, db_id: int, table: str) -> int:
    for ds in api.find("dataset", "table_name", table):
        if ds.get("database", {}).get("id") == db_id:
            api.put(f"/api/v1/dataset/{ds['id']}/refresh", {})
            return ds["id"]
    return api.post("/api/v1/dataset/", {"database": db_id, "schema": SCHEMA, "table_name": table})["id"]


COLUMN_LABELS = {
    "player_name": "Player", "position_name": "Position", "position": "Pos",
    "acute_load": "Acute load (7d)", "chronic_load": "Chronic load (28d avg)", "acwr": "ACWR",
    "risk_band": "Status", "match_date": "Match date", "week_start": "Week", "segment": "Minutes",
    "result": "Result", "opponent": "Opponent",
}
COLUMN_KEYS = ("id", "column_name", "verbose_name", "type", "is_dttm", "groupby", "filterable",
               "expression", "description", "python_date_format", "is_active", "extra")


def label_columns(api: Superset, dataset_id: int) -> None:
    columns = api.get(f"/api/v1/dataset/{dataset_id}")["result"]["columns"]
    updated = []
    for col in columns:
        col = {k: col.get(k) for k in COLUMN_KEYS if k in col}
        col["verbose_name"] = COLUMN_LABELS.get(col["column_name"], col.get("verbose_name"))
        updated.append({k: v for k, v in col.items() if v is not None})
    api.put(f"/api/v1/dataset/{dataset_id}", {"columns": updated})


def remove_previous(api: Superset, names: list[str]) -> None:
    for dash in api.find("dashboard", "slug", DASHBOARD_SLUG):
        api.delete(f"/api/v1/dashboard/{dash['id']}")
    for name in names:
        for chart in api.find("chart", "slice_name", name):
            api.delete(f"/api/v1/chart/{chart['id']}")


def bootstrap(superset_url: str, username: str, password: str, analytics_uri: str) -> int:
    api = Superset(superset_url, username, password)
    db_id = ensure_database(api, analytics_uri)
    dataset_ids = {t: ensure_dataset(api, db_id, t) for t in DATASETS}
    for ds_id in dataset_ids.values():
        label_columns(api, ds_id)
    log.info("datasets: %s", dataset_ids)

    specs = chart_specs()
    remove_previous(api, [name for _ds, name, _p in specs.values()])

    chart_ids, names = {}, {}
    for key, (dataset, name, params) in specs.items():
        ds_id = dataset_ids[dataset]
        params = {**params, "datasource": f"{ds_id}__table"}
        chart_ids[key] = api.post("/api/v1/chart/", {
            "slice_name": name, "viz_type": params["viz_type"], "datasource_id": ds_id,
            "datasource_type": "table", "params": json.dumps(params),
        })["id"]
        names[key] = name
        log.info("chart %-45s id %s", name, chart_ids[key])

    team_charts = [chart_ids[k] for k, (ds, _n, _p) in specs.items() if ds == "v_team_match"]
    metadata = {
        "color_scheme": "supersetColors",
        "refresh_frequency": 0,
        "cross_filters_enabled": True,
        "native_filter_configuration": [
            native_filter("NATIVE_FILTER-position", "Position", dataset_ids["v_player_match"],
                          "position", team_charts),
            native_filter("NATIVE_FILTER-player", "Player", dataset_ids["v_player_match"],
                          "player_name", team_charts),
        ],
        "default_filters": "{}",
        "chart_configuration": {},
        "label_colors": {"W": "#1FA8C9", "D": "#FCC700", "L": "#E04355"},
    }
    dashboard_id = api.post("/api/v1/dashboard/", {
        "dashboard_title": DASHBOARD_TITLE, "slug": DASHBOARD_SLUG, "published": True,
        "position_json": json.dumps(build_position_json(chart_ids, names)),
        "json_metadata": json.dumps(metadata),
    })["id"]
    for cid in chart_ids.values():
        api.put(f"/api/v1/chart/{cid}", {"dashboards": [dashboard_id]})
    log.info("dashboard ready: %s/superset/dashboard/%s/", superset_url.rstrip("/"), DASHBOARD_SLUG)
    return dashboard_id


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--superset-url", default=os.environ.get("SUPERSET_URL", "http://localhost:8088"))
    p.add_argument("--username", default=os.environ.get("SUPERSET_ADMIN_USER", "admin"))
    p.add_argument("--password", default=os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin"))
    p.add_argument("--analytics-uri", default=os.environ.get("ANALYTICS_DATABASE_URL"),
                   help="SQLAlchemy URI Superset should use to reach the analytics database")
    a = p.parse_args()
    if not a.analytics_uri:
        p.error("--analytics-uri or ANALYTICS_DATABASE_URL is required")
    bootstrap(a.superset_url, a.username, a.password, a.analytics_uri)


if __name__ == "__main__":
    main()
