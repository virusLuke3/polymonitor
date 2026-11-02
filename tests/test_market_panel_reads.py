import json
import multiprocessing
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.cache import CacheState
from api.config import ClickHouseSettings
from api.context import RuntimeResources
from api.read_budget import take_read_token, try_permit
from api.services.panel_read_cache import NAMESPACE, PanelReadCache
from api.services.market_service import MarketPanelReader
from api.services import panel_trade_reader
from runtime.snapshot_store import SnapshotStore


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYDATA_READ_BUDGET_DIR", str(tmp_path / "budgets"))
    resources = RuntimeResources()
    store = SnapshotStore(str(tmp_path / "cache.sqlite"), busy_timeout_ms=20)
    app = Mock()
    runtime = SimpleNamespace(resources=resources, app=app, SNAPSHOT_STORE=store,
                              cache=CacheState(resources, app, store),
                              SETTINGS=SimpleNamespace(clickhouse=ClickHouseSettings()))
    yield runtime
    resources.close()


def test_cold_parallel_read_has_one_builder_and_no_waiting_workers(runtime):
    cache = PanelReadCache(runtime)
    started, release = Event(), Event()
    def build():
        started.set()
        assert release.wait(2)
        return {"items": [1]}
    builder = Mock(side_effect=build)
    with ThreadPoolExecutor(max_workers=8) as executor:
        first = executor.submit(cache.get, "catalog", 1, builder, ttl=20, max_age=60)
        assert started.wait(1)
        others = [executor.submit(cache.get, "catalog", 1, builder, ttl=20, max_age=60) for _ in range(20)]
        assert all(f.result(1)["status"] == "warming" for f in others)
        release.set()
        assert first.result()["items"] == [1]
    assert builder.call_count == 1
    assert cache.get("catalog", 1, builder, ttl=20, max_age=60)["items"] == [1]


def test_failure_cooldown_and_stale_age_do_not_overwrite_last_good(runtime):
    cache = PanelReadCache(runtime)
    key = json.dumps(["flow", 1], separators=(",", ":"))
    runtime.SNAPSHOT_STORE.set(NAMESPACE, key, {"items": [1], "generatedAt": "old-source-time"}, 1)
    with sqlite3.connect(runtime.SNAPSHOT_STORE.db_path) as db:
        db.execute("UPDATE panel_snapshots SET expires_at=?, updated_at=?", (int(time.time()) - 1, int(time.time()) - 5))
    failed = Mock(side_effect=TimeoutError())
    result = cache.get("flow", 1, failed, ttl=8, max_age=60)
    assert result["status"] == "stale" and result["generatedAt"] == "old-source-time"
    runtime.resources.close()
    assert failed.call_count == 1
    for _ in range(30):
        assert cache.get("flow", 1, failed, ttl=8, max_age=60)["items"] == [1]
    assert failed.call_count == 1
    with sqlite3.connect(runtime.SNAPSHOT_STORE.db_path) as db:
        db.execute("UPDATE panel_snapshots SET updated_at=? WHERE namespace=?", (int(time.time()) - 90, NAMESPACE))
    assert cache.get("flow", 1, failed, ttl=8, max_age=60)["items"] == []


def _hold_permit(ready, release):
    permit = try_permit("test-global", 1)
    ready.set()
    release.wait(5)
    permit.close()


def test_worker_exit_releases_global_admission(runtime):
    ctx = multiprocessing.get_context("fork")
    ready, release = ctx.Event(), ctx.Event()
    process = ctx.Process(target=_hold_permit, args=(ready, release))
    process.start()
    try:
        assert ready.wait(2)
        assert try_permit("test-global", 1) is None
        process.terminate()
        process.join(2)

        with try_permit("test-global", 1):
            assert try_permit("test-global", 1) is None
    finally:
        if process.is_alive():
            process.kill()
        process.join(2)


def test_unique_keys_cannot_bypass_global_source_rate(runtime, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("api.read_budget.time.monotonic", lambda: clock[0])
    assert take_read_token("source", per_second=1, burst=2)
    assert take_read_token("source", per_second=1, burst=2)
    assert not any(take_read_token("source", per_second=1, burst=2) for _ in range(100))
    clock[0] += 1
    assert take_read_token("source", per_second=1, burst=2)
    assert not take_read_token("source", per_second=1, burst=2)


def test_panel_cache_capacity_does_not_prune_other_namespaces(runtime):
    store = runtime.SNAPSHOT_STORE
    store.set("unrelated", "keep", {"id": 1}, 60)
    for i in range(12):
        store.set(NAMESPACE, str(i), {"id": i}, 60, max_entries=4)
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT count(*) FROM panel_snapshots WHERE namespace=?", (NAMESPACE,)).fetchone()[0] == 4
    assert store.get("unrelated", "keep") == {"id": 1}


def test_empty_flow_is_a_fixed_window_not_an_expanding_scan(runtime, monkeypatch):
    reader = MarketPanelReader(runtime)
    reader.record = Mock(return_value={"yes_token_id": "1", "no_token_id": "2"})
    runtime.market_context = {"app": runtime.app}
    calls = []
    def query(ctx, sql, **kwargs):
        calls.append(sql)
        assert ctx['_resources'].clickhouse.max_threads == 1
        assert ctx['_resources'].clickhouse.max_bytes_to_read == (4 if len(calls) == 1 else 56) * 1024**2
        return [{"block_number": 90000000, "timestamp": "2026-11-02T00:00:00Z"}] if len(calls) == 1 else []
    monkeypatch.setattr(panel_trade_reader.ch, "_query_json_rows", query)
    monkeypatch.setattr(panel_trade_reader.semantics, "annotate_raw_trade_rows", lambda _, rows: rows)
    result = reader.flow(1)
    assert result["items"] == [] and result["status"] == "ok"
    assert len(calls) == 2
    assert "canonical_token_id IN" in calls[1]
    assert "BETWEEN 89913601 AND 90000000" in calls[1]
    assert result["coverage"]["globalCompleteness"] == "NOT_PROVEN"


def test_queries_are_readonly_and_release_leases_on_timeout(runtime):
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.execute.side_effect = lambda sql, *args: (_ for _ in ()).throw(TimeoutError()) if sql == "SELECT expensive" else None
    runtime.SETTINGS.database = SimpleNamespace(sqlite_path="")
    runtime._api_connection_factory = Mock(return_value=connection)
    with pytest.raises(TimeoutError):
        MarketPanelReader(runtime).query("SELECT expensive")
    statements = [part for c in cursor.execute.call_args_list for part in c.args[0].split('; ')]
    assert "SET TRANSACTION READ ONLY" in statements
    assert "SET LOCAL statement_timeout = '1000ms'" in statements
    connection.close.assert_called_once()


def test_receipt_cache_deduplicates_without_changing_source_evidence(runtime):
    reader = MarketPanelReader(runtime)
    shared = {"plan": "evidence" * 80_000}
    rows = [{"market_id": i, "receipt_plan_json": shared, "receipt_record_json": {"id": i},
             "receipt_before_images_json": None} for i in range(2)]
    # Repeated documents exceed the budget; unique evidence fits it.
    import copy
    reader.query = Mock(side_effect=lambda *args: copy.deepcopy(rows))
    assert reader.semantic_query("SELECT evidence", (1, 2)) == rows
    assert reader.semantic_query("SELECT evidence", (1, 2)) == rows
    reader.query.assert_called_once()




def test_worker_pool_cannot_reserve_sibling_connection_share(runtime, monkeypatch):
    from api.db_pool import build_api_connection_factory
    monkeypatch.setenv("POLYDATA_GUNICORN_WORKERS", "2")
    monkeypatch.setenv("POLYDATA_API_POSTGRES_POOL_SIZE", "16")
    factory = Mock(side_effect=lambda **kwargs: Mock())
    connect = build_api_connection_factory(factory, lambda: "postgres")
    first, second = connect(), connect()
    try:
        with pytest.raises(TimeoutError):
            connect()
        assert factory.call_count == 2
        first.close()
        third = connect()
        third.close()
        assert factory.call_count == 2
    finally:
        first.close()
        second.close()
        connect.close()


def test_catalog_caps_page_and_ranks_current_quotes_without_a_newest_market_window(runtime):
    reader = MarketPanelReader(runtime)
    reader.query = Mock(return_value=[])
    payload = reader.catalog(page_size=10000)
    sql, params = reader.query.call_args.args
    assert params == (101,)
    assert 'core.market_quote_current' in sql and 'q.volume_24h DESC NULLS LAST' in sql
    assert 'market_list_serving' not in sql and 'market_latest_prices' not in sql
    assert '5000' not in sql
    assert payload['pagination']['pageSize'] == 100
    with pytest.raises(ValueError):
        reader.catalog(page=2)
    assert reader.query.call_count == 1


def test_catalog_sort_cache_is_separate_and_unsupported_sorts_fail_before_query(runtime):
    reader = MarketPanelReader(runtime)
    reader.query = Mock(return_value=[])
    for sort in ('volume', 'new', 'close'):
        assert reader.catalog(sort=sort)['sort'] == sort
        assert reader.catalog(sort=sort)['sort'] == sort
    assert reader.query.call_count == 3
    with pytest.raises(ValueError):
        reader.catalog(sort='trades')
    assert reader.query.call_count == 3


def test_catalog_does_not_read_missing_volume_from_metadata_or_invent_trade_prices():
    item = MarketPanelReader._item({'id': 7, 'catalog_payload': {'volume24hr': 999},
        'latest_yes_price': '0.9', 'volume_24h': None, 'quote_observed_at': 'observed',
        'quote_updated_at': 'source-time', 'quote_token_ids': ['1', '2'],
        'quote_prices': ['0.2', '0.81'], 'quote_labels': ['Yes', 'No']})
    assert item['volume24h'] is None and item['latestPrice'] is None
    assert item['tradeCount24h'] is None and item['lastTradeAt'] is None
    assert item['_catalogQuote']['prices'] == ['0.2', '0.81']
    assert item['observedAt'] == 'observed' and item['quoteUpdatedAt'] == 'source-time'
    assert MarketPanelReader._item({'volume_24h': 0})['volume24h'] == 0


def test_compatibility_book_resolves_identity_then_uses_native_adapter(runtime, monkeypatch):
    reader = MarketPanelReader(runtime)
    reader.record = Mock(return_value={'yes_token_id': '1', 'no_token_id': '2', 'title': 'Market'})
    source = Mock(return_value={'bookStatus': 'stale'})
    monkeypatch.setattr('api.services.lob_service.get_runtime_lob_by_token_payload', source)
    assert reader.book(7) == {'bookStatus': 'stale'}
    source.assert_called_once_with('1', no_token_id='2', market_title='Market', market_id=7)


def test_bootstrap_and_panel_health_do_not_read_sources(tmp_path):
    from dataclasses import replace
    from api.app import create_app
    from api.config import load_api_settings
    connect = Mock(side_effect=AssertionError('No source IO'))
    app = create_app(replace(load_api_settings(), snapshot_sqlite_path=str(tmp_path / 'snapshots.sqlite')), connection_factory=connect)
    runtime = app.extensions['polydata_runtime']
    try:
        client = app.test_client()
        bootstrap = client.get('/bootstrap')
        assert bootstrap.status_code == 200
        assert bootstrap.json['activeMarketsPreview'] == []
        assert client.get('/health/panels').json['scope'] == 'recent-reads-only'
        connect.assert_not_called()
    finally:
        runtime.close()


def test_http_mcp_and_linking_share_the_reader(tmp_path, monkeypatch):
    from dataclasses import replace
    from api import bindings
    from api.app import create_app
    from api.config import load_api_settings
    captured = {}
    original = bindings.mcp_routes.create_mcp_blueprint
    def capture(deps):
        captured['mcp'] = deps
        return original(deps)
    monkeypatch.setattr(bindings.mcp_routes, 'create_mcp_blueprint', capture)
    monkeypatch.setattr('api.services.outcome_semantics_service.sanitize_public_market_payload', lambda ctx, payload, **kw: payload)
    monkeypatch.setattr(MarketPanelReader, 'detail', lambda self, market_id: {'market': {'id': market_id}, 'owner': 'single-reader'})
    app = create_app(replace(load_api_settings(), snapshot_sqlite_path=str(tmp_path / 'snapshots.sqlite')), connection_factory=Mock(side_effect=AssertionError('No IO')))
    runtime = app.extensions['polydata_runtime']
    try:
        reader = runtime.panel_reader
        assert captured['mcp'].search_markets == reader.search
        assert captured['mcp'].get_market_workspace == reader.workspace
        assert captured['mcp'].get_market_oracle == reader.oracle
        reader.search = Mock(return_value={'items': []})
        assert runtime.breaking_event_radar.search_markets('weather') == {'items': []}
        reader.search.assert_called_once_with('weather', limit=10)
        for path in ('detail', 'focus-tile'):
            assert app.test_client().get(f'/markets/7/{path}').json['owner'] == 'single-reader'
        reader.record = Mock(side_effect=LookupError('Missing market'))
        for path in ('/markets/8', '/runtime/lob/8'):
            assert app.test_client().get(path).status_code == 404
    finally:
        runtime.close()
