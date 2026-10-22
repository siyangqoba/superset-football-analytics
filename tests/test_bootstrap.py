import json

from bootstrap_dashboard import DATASETS, LAYOUT, build_position_json, chart_specs, rison


def test_rison_encoding():
    assert rison({"filters": [{"col": "slug", "opr": "eq", "value": "it's!"}], "page_size": 100}) == \
        "(filters:!((col:'slug',opr:'eq',value:'it!'s!!')),page_size:100)"
    assert rison(True) == "!t"


def test_every_chart_is_placed_exactly_once():
    specs = chart_specs()
    placed = [key for _tab, rows in LAYOUT for row in rows for key, _w, _h in row]
    assert sorted(placed) == sorted(specs)


def test_rows_fit_the_12_column_grid():
    for _tab, rows in LAYOUT:
        for row in rows:
            assert sum(w for _k, w, _h in row) <= 12


def test_charts_use_known_datasets_and_valid_json():
    for key, (dataset, name, params) in chart_specs().items():
        assert dataset in DATASETS, key
        assert params["viz_type"]
        json.dumps(params)
        assert name


def test_position_json_links_parents_and_charts():
    specs = chart_specs()
    ids = {k: i for i, k in enumerate(specs, start=100)}
    pos = build_position_json(ids, {k: v[1] for k, v in specs.items()})
    charts = [v for v in pos.values() if isinstance(v, dict) and v.get("type") == "CHART"]
    assert {c["meta"]["chartId"] for c in charts} == set(ids.values())
    for node_id, node in pos.items():
        if not isinstance(node, dict):
            continue
        for child in node.get("children", []):
            assert pos[child]["parents"][-1] == node_id
