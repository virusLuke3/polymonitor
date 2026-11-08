"""Business snapshots require SQLite acceptance; source caches remain optional."""
from types import SimpleNamespace

import pytest

from api.services import geo_sanctions_shock_service as geo_service
from api.services import global_weather_map_service as weather_service
from runtime import geo_sanctions_shock_watcher as geo
from runtime import global_weather_map_watcher as weather
from runtime.seed_meta import SnapshotPublicationError


class Store:
    def __init__(self, accepted=True, payload=None):
        self.accepted, self.payload, self.writes = accepted, payload, []

    def set(self, namespace, key, payload, ttl):
        self.writes.append(payload)
        if isinstance(self.accepted, Exception):
            raise self.accepted
        if self.accepted:
            self.payload = payload
        return self.accepted

    def get(self, *args):
        return self.payload

    def get_stale(self, *args):
        return self.payload


class BrokenMirror:
    def __init__(self):
        self.writes = 0

    def set(self, *args, **kwargs):
        self.writes += 1
        raise ConnectionError('mirror unavailable')

    def get(self, *args):
        raise AssertionError('SQLite must be authoritative')


def watcher(kind, store, mirror, monkeypatch):
    cls = weather.GlobalWeatherMapWatcher if kind == 'weather' else geo.GeoSanctionsShockWatcher
    value = cls.__new__(cls)
    value.settings = SimpleNamespace(global_weather_map_ttl_seconds=300, geo_shock_ttl_seconds=900)
    value.snapshot_store, value.redis_client, value.redis_prefix = store, mirror, ''
    value.interval_seconds = 3600
    value.published_meta = []
    payload = {'generatedAt': '2026-11-06T00:00:00Z', 'status': 'ok',
               'items': [{'cityId': 'test', 'currentTemp': 20}],
               'sources': {'openMeteo' if kind == 'weather' else 'federalRegister': 'ok'}}
    if kind == 'weather':
        value.previous = lambda: {}
        value.context = lambda: {}
        value.store_meta = lambda **kwargs: value.published_meta.append(kwargs)
        monkeypatch.setattr(weather_service, 'build_global_weather_map_payload', lambda *a, **kw: payload)
        monkeypatch.setattr(weather, 'publish_cached_panel_snapshot', lambda *a: False)
    else:
        value.load_previous_payload = lambda: {}
        value.build_payload = lambda: payload
        value.store_seed_meta = lambda **kwargs: value.published_meta.append(kwargs)
    return value


@pytest.mark.parametrize('kind', ['geo', 'weather'])
@pytest.mark.parametrize('refusal', [False, OSError('disk failure')])
def test_rejected_business_write_cannot_report_success_or_send_telegram(kind, refusal, monkeypatch):
    mirror = BrokenMirror()
    value = watcher(kind, Store(refusal), mirror, monkeypatch)
    monkeypatch.setattr(weather, 'publish_cached_panel_snapshot', lambda *a: pytest.fail('unpublished snapshot sent'))
    with pytest.raises(SnapshotPublicationError):
        value.run_once()
    assert not value.published_meta and mirror.writes == 0


@pytest.mark.parametrize('kind', ['geo', 'weather'])
@pytest.mark.parametrize('with_mirror', [False, True])
def test_optional_mirror_failure_does_not_discard_accepted_sqlite_snapshot(kind, with_mirror, monkeypatch):
    store = Store()
    value = watcher(kind, store, BrokenMirror() if with_mirror else None, monkeypatch)
    result = value.run_once()
    assert result['status'] == 'stored' and store.payload['generatedAt'] == '2026-11-06T00:00:00Z'
    assert value.published_meta[0]['status'] == 'ok'


def test_business_reads_prefer_sqlite_and_do_not_republish_mirror():
    payload = {'generatedAt': '2026-11-06T00:00:00Z', 'items': []}
    store = Store(payload=payload)
    def mirror(*args):
        pytest.fail('mirror must not override authoritative snapshot')
    ctx = {'SNAPSHOT_STORE': store, 'get_cached_json': mirror, 'set_cached_json': mirror,
           'utc_now_iso': lambda: '2026-11-06T00:00:00Z'}
    assert geo_service._seeded_payload_from_cache(ctx) is payload
    dependencies = SimpleNamespace(snapshot_store=store, get_cached_json=mirror)
    assert weather_service._read_seeded_snapshot(dependencies, ttl_seconds=900)['cacheMode'] == 'sqlite-seed'
    for cls, method in [(geo.GeoSanctionsShockWatcher, 'load_previous_payload'), (weather.GlobalWeatherMapWatcher, 'previous')]:
        value = cls.__new__(cls)
        value.snapshot_store, value.redis_client = store, BrokenMirror()
        assert getattr(value, method)() is payload
    assert store.writes == []


@pytest.mark.parametrize('kind', ['geo', 'weather'])
def test_first_failure_has_no_success_clock(kind):
    meta = []
    storage = SimpleNamespace(load=lambda *a: None, store=lambda *a: meta.append(a[2]))
    if kind == 'weather':
        value = weather.GlobalWeatherMapWatcher.__new__(weather.GlobalWeatherMapWatcher)
        value.interval_seconds, value.seed_meta_store = 3600, storage
        value.store_meta(status='error', record_count=0, preserve=True)
    else:
        value = geo.GeoSanctionsShockWatcher.__new__(geo.GeoSanctionsShockWatcher)
        value.seed_meta_store = storage
        value.store_seed_meta(status='error', record_count=0, preserve_last_success=True)
    assert meta[0]['lastSuccessAt'] is None


@pytest.mark.parametrize('kind', ['geo', 'weather'])
def test_watchers_can_start_without_redis_configuration(kind, tmp_path):
    settings = SimpleNamespace()
    common = {'redis_url': '', 'redis_prefix': '', 'snapshot_sqlite_path': str(tmp_path / 'snapshots.sqlite'),
              'settings': settings}
    if kind == 'weather':
        value = weather.GlobalWeatherMapWatcher(**common, interval_seconds=3600)
        assert value.redis_client is None
        value.close()
    else:
        value = geo.GeoSanctionsShockWatcher(**common)
        assert value.redis_client is None
        value.requests.close()
