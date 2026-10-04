from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from api.services import macro_cpi_panels_service as drivers
from api.services import macro_cpi_registry_service as registry
from api.services.macro_data_contract import describe_series, monthly_metric, shift_month


def cpi_context(now="2026-10-04T12:00:00Z"):
    calls = []

    def fetch(url, **kwargs):
        series = parse_qs(urlsplit(url).query)["id"][0]
        calls.append(series)
        rows = [f"{shift_month('2025-08', i)}-01,{100 + i}" for i in range(14)]
        return "observation_date," + series + "\n" + "\n".join(rows)

    return {"utc_now_iso": lambda: now, "http_text_get": fetch, "calls": calls}


def cpi_rows():
    calendar = registry._calendar_rows({"items": [{"id": "cpi-2026-09", "kind": "CPI", "title": "CPI",
        "releaseAt": "2026-10-14T12:30:00Z", "referencePeriod": "September 2026"}]})
    nowcast = registry._nowcast_rows({"generatedAt": "2026-10-04T11:00:00Z", "monthlyPeriods": {
        "monthOverMonth": [{"Month": "October 2026", "CPI": "9.99", "Core CPI": "9.99"},
                           {"Month": "September 2026", "CPI": "0.21", "Core CPI": "0.19"}],
        "yearOverYear": [{"Month": "October 2026", "CPI": "9.99", "Core CPI": "9.99"},
                         {"Month": "September 2026", "CPI": "3.12", "Core CPI": "2.55"}]}})
    return calendar + nowcast


def test_cpi_selects_matching_month_not_first_row_and_correct_adjustment():
    ctx = cpi_context()
    result = registry._compose_cpi_release_events(registry.MacroCpiRegistryDependencies.from_context(ctx), cpi_rows())
    events = {event["key"]: event for event in result["events"]}
    assert events["headline-mom"]["forecast"] == .21
    assert events["headline-yoy"]["forecast"] == 3.12
    assert all(event["actual"] is None and event["previous"] is not None for event in events.values())
    assert set(ctx["calls"]) == {"CPIAUCNS", "CPILFENS", "CPIAUCSL", "CPILFESL"}
    assert events["headline-mom"]["adjustment"] == "SA"
    assert events["headline-yoy"]["adjustment"] == "NSA"


def test_actual_and_previous_bound_to_reference_period_and_freeze_before_release():
    ctx = cpi_context()
    before = registry._compose_cpi_release_events(registry.MacroCpiRegistryDependencies.from_context(ctx), cpi_rows())
    ctx = {**cpi_context("2026-10-14T14:00:00Z"), "previousRegistry": before}
    after = registry._compose_cpi_release_events(registry.MacroCpiRegistryDependencies.from_context(ctx), cpi_rows())
    assert all(event["actual"] is not None and event["surprise"] is not None for event in after["events"])
    assert after["events"][0]["forecastAsOf"] == "2026-10-04T11:00:00Z"
    # An initial post-release fetch has no frozen pre-release forecast: no fabricated surprise.
    first_after = registry._compose_cpi_release_events(registry.MacroCpiRegistryDependencies.from_context(cpi_context("2026-10-14T14:00:00Z")), cpi_rows())
    assert all(event["forecast"] is None and event["surprise"] is None for event in first_after["events"])


def test_missing_target_month_does_not_use_latest_actual_or_positional_year():
    observations = [{"date": "2026-07-01", "value": 100}, {"date": "2026-09-01", "value": 102}]
    assert monthly_metric(observations, "2026-09", "mom") is None
    assert monthly_metric(observations, "2026-09", "yoy") is None
    assert monthly_metric(observations, "2026-08", "mom") is None


@pytest.mark.parametrize("series,unit,metric,dates,values,expected,label", [
    ("UNRATE", "%", "level", ["2026-07-01", "2026-08-01"], [4.1, 4.2], .1, "pp MoM"),
    ("DGS2", "%", "level", ["2026-10-01", "2026-10-02"], [3.5, 3.6], 10, "bp vs prior observation"),
    ("PAYEMS", "k", "delta", ["2026-07-01", "2026-08-01"], [159000, 159029], 29, "K persons MoM"),
    ("ICSA", "k", "delta", ["2026-09-19", "2026-09-26"], [210000, 212000], 2000, "persons WoW"),
    ("GDPC1", "bil", "pct", ["2026-01-01", "2026-04-01"], [100, 101], 4.06, "% QoQ annualized"),
])
def test_series_changes_keep_their_unit_and_period(series, unit, metric, dates, values, expected, label):
    result = describe_series({"seriesId": series, "unit": unit, "metric": metric, "label": series},
                             [dict(date=d, value=v) for d, v in zip(dates, values)], "2026-10-04T12:00:00Z")
    assert result["changeValue"] == pytest.approx(expected, abs=.001)
    assert result["changeLabel"].endswith(label)
    assert result["publishedAt"] is None
    if series == "PAYEMS":
        assert result["valueLabel"] == "29.0K" and result["levelLabel"] == "159.029M"
    if series == "GDPC1":
        assert result["periodLabel"] == "2026 Q2"


def test_import_turnover_is_context_not_price_pressure():
    result = describe_series({"seriesId": "IMPGS", "unit": "bil", "metric": "pct", "label": "Imports"},
                             [{"date": "2026-01-01", "value": 4000}, {"date": "2026-04-01", "value": 4200}], "2026-10-04T12:00:00Z")
    assert result["contextOnly"] is True
    assert result["valueLabel"] == "$4,200.0B"
    assert result["changeWindow"] == "QoQ"


def test_api_seed_hit_and_miss_never_call_external_sources(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("API must not compute or fetch macro data")
    monkeypatch.setattr(registry, "_compose_cpi_release_events", fail)
    monkeypatch.setattr(registry, "build_macro_cpi_registry_payload", fail)
    seed = {"schemaVersion": 2, "status": "ok", "generatedAt": "2026-10-04T12:00:00Z", "items": [],
            "events": [{"key": "headline-yoy", "forecast": 3.12}], "eventSummary": {"forecastCount": 1}}
    result = registry.get_cpi_release_command_center_snapshot({"get_cached_json": lambda *args: seed})
    assert result["events"] == seed["events"]
    assert result["summary"]["forecastCount"] == 1
    miss = registry.get_cpi_release_command_center_snapshot({})
    assert miss["cacheMode"] == "seed-miss" and miss["generatedAt"] is None


def test_duplicate_curve_and_heterogeneous_summary_are_not_ranked():
    rows = [{"key": "fed-curve", "type": "series", "date": "2026-10-02", "metadata": {"seriesId": "T10Y2Y"}, "change": 10, "tone": "hot"},
            {"key": "growth-curve", "type": "series", "date": "2026-10-02", "metadata": {"seriesId": "T10Y2Y"}, "change": 10, "tone": "cool"},
            {"key": "oil", "change": 1000, "tone": "hot"}]
    ranked = registry._rank_rows(rows)
    assert len(ranked) == 2
    summary = registry._summarize("fed", ranked, {"fed": "ok", "fed.curve": "ok", "growth.gdp": "error"}, {})
    assert summary["topMover"] is None
    assert summary["signal"] == "OBSERVED MACRO DATA"
    assert summary["coverage"] == 1 and summary["sourceCount"] == 2


def test_partial_fred_failure_preserves_original_observation_and_clock():
    item = {"key": "unrate", "seriesId": "UNRATE", "value": 4.2, "date": "2026-08-01", "fetchedAt": "2026-10-04T06:00:00Z"}
    ctx = {"get_cached_json": lambda *args: {"items": [item]}, "http_text_get": lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
           "http_json_get": lambda *args, **kwargs: {}, "utc_now_iso": lambda: "2026-10-04T12:00:00Z"}
    result = drivers.build_macro_cpi_panel_payload(ctx, "labor-wage-services-pressure", limit=60)
    kept = next(row for row in result["items"] if row["key"] == "unrate")
    assert kept["retained"] is True and kept["fetchedAt"] == item["fetchedAt"]
    assert result["sources"]["unrate"] == "error" and result["status"] == "degraded"


def test_nowcast_html_parser_keeps_all_months(monkeypatch):
    from bs4 import BeautifulSoup
    from api.services import runtime_service
    html = '<table><caption>Month-over-month percent change</caption><tr><th>Month</th><th>CPI</th></tr><tr><td>October 2026</td><td>0.3</td></tr><tr><td>September 2026</td><td>0.1</td></tr></table>'
    deps = SimpleNamespace(settings=SimpleNamespace(cleveland_fed_nowcast_url='https://example.test'),
        utc_now_iso=lambda: '2026-10-04T12:00:00Z', beautiful_soup=BeautifulSoup,
        requests_lib=SimpleNamespace(get=lambda *a, **k: SimpleNamespace(text=html, raise_for_status=lambda: None)))
    monkeypatch.setattr(runtime_service, '_dependencies', lambda ctx: deps)
    result = runtime_service.fetch_live_inflation_nowcast_payload({})
    assert result['monthOverMonth']['Month'] == 'October 2026'  # Other consumers stay compatible.
    assert result['monthlyPeriods']['monthOverMonth'][1]['Month'] == 'September 2026'


def test_cpi_event_inputs_are_not_truncated_by_display_limit():
    ctx = cpi_context()
    result = registry._payload(registry.MacroCpiRegistryDependencies.from_context(ctx),
        'cpi-release-command-center', cpi_rows(), {'calendar': 'ok', 'nowcast': 'ok'}, limit=1)
    assert len(result['items']) == 1
    assert result['summary']['forecastCount'] == 4
    assert result['summary']['previousCount'] == 4


def test_optional_employment_calendar_does_not_fail_verified_cpi(monkeypatch):
    ctx = cpi_context()
    fixture_rows = cpi_rows()
    monkeypatch.setattr(registry.cpi_release_calendar_service, 'get_cpi_release_calendar_snapshot',
        lambda *a, **k: {'status': 'degraded', 'sources': {'blsCpi': 'ok', 'blsEmployment': 'fallback'}, 'items': []})
    monkeypatch.setattr(registry, '_calendar_rows', lambda payload: fixture_rows[:1])
    monkeypatch.setattr(registry, '_inflation_nowcast_seeded_snapshot', lambda deps: {'status': 'ok'})
    monkeypatch.setattr(registry, '_nowcast_rows', lambda payload: fixture_rows[1:])
    result = registry.build_cpi_release_command_center_snapshot(ctx)
    assert result['status'] == 'ok'
    assert result['sources']['calendar.blsCpi'] == 'ok'
    assert result['optionalSources']['calendar.blsEmployment'] == 'fallback'
    assert result['summary']['forecastCount'] == result['summary']['previousCount'] == 4


def test_component_coverage_does_not_depend_on_unused_trade_turnover_or_policy(monkeypatch):
    monkeypatch.setattr(registry.energy_gasoline_shock_service, 'get_energy_gasoline_shock_snapshot',
        lambda *a, **k: {'status': 'ok', 'sources': {'eia': 'ok'}, 'items': []})
    monkeypatch.setattr(registry.food_retail_basket_service, 'get_food_retail_basket_snapshot',
        lambda *a, **k: {'status': 'ok', 'sources': {'fred': 'ok'}, 'items': []})
    monkeypatch.setattr(drivers, 'get_shelter_rent_oer_pressure_snapshot',
        lambda *a, **k: {'status': 'ok', 'sources': {'rent': 'ok'}, 'items': []})
    specs = drivers.PANEL_CONFIGS['supply-tariff-import-watch']['series']
    states = {spec['key']: 'ok' for spec in specs}
    states.update(imports='error', export_import='error', federal_register='error')
    monkeypatch.setattr(drivers, 'get_supply_tariff_import_watch_snapshot',
        lambda *a, **k: {'status': 'degraded', 'sources': states,
                        'items': [{'key': 'cpi_commodities', 'seriesId': 'CUSR0000SAC', 'value': 100}]})
    result = registry.build_cpi_components_pressure_registry_snapshot({})
    assert result['status'] == 'ok'
    assert 'goods.imports' not in result['sources']
    assert 'goods.federal_register' not in result['sources']
    states['cpi_commodities'] = 'error'
    assert registry.build_cpi_components_pressure_registry_snapshot({})['status'] == 'degraded'
