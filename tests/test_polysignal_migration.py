from copy import deepcopy
from threading import Event

import pytest
from flask import Flask

from api.context import RuntimeResources
from api.routes.runtime_panels import RuntimePanelRouteDependencies, create_runtime_panels_blueprint
from api.runtime_panels.registry import get_panel_by_id, get_panel_ids, get_panel_by_route
from api.runtime_panels.types import RuntimePanelContext
from api.services import polysignal_feed_service, signal_service
from api.services.signal_reads import SignalReadPending, read_verified_seed
from runtime.signals_watcher import COMPONENTS


def test_four_real_signal_channels_are_admitted_and_fifth_is_bounded():
    resources = RuntimeResources(shutdown_timeout_seconds=.1)
    ctx = {'_resources': resources}
    release = Event()
    try:
        channels = [spec['namespace'] for spec in COMPONENTS.values()]
        assert len(channels) == 4
        def blocked(seed):
            release.wait(2)
            return seed
        for channel in channels:
            with pytest.raises(SignalReadPending, match='still running'):
                read_verified_seed(ctx, channel, {'channel': channel}, blocked, wait_seconds=.01)
        with pytest.raises(SignalReadPending, match='capacity'):
            read_verified_seed(ctx, 'extra', {}, blocked, wait_seconds=.01)
        release.set()
        for channel in channels:
            assert read_verified_seed(ctx, channel, {'channel': channel}, blocked) == {'channel': channel}
        # Retained successful checks must not shut out PolySignal on refresh.
        assert read_verified_seed(ctx, polysignal_feed_service.SNAPSHOT_NAMESPACE, {'new': True}, lambda x: x) == {'new': True}
    finally:
        release.set()
        resources.close()


def test_aliases_use_one_canonical_panel_and_keep_legacy_batch_keys():
    payload = {'items': [], 'status': 'empty', 'generatedAt': '2026-11-03T00:00:00Z'}
    panel = get_panel_by_id('polysignal-feed')
    assert panel is get_panel_by_id('polybeats-feed')
    assert panel is get_panel_by_route('/runtime/signals/polybeats')
    assert 'polybeats-feed' not in get_panel_ids()
    app = Flask(__name__)
    app.register_blueprint(create_runtime_panels_blueprint(RuntimePanelRouteDependencies(
        panel_context=RuntimePanelContext.from_context({'get_polysignal_snapshot': lambda **_: deepcopy(payload)}),
        utc_now_iso=lambda: '2026-11-03T00:00:00Z', natural_hazard_map_snapshot=None,
        natural_hazard_event_detail=None, natural_hazard_related_markets=None, aviation_viewport_snapshot=None,
    )))
    client = app.test_client()
    for route in ['/runtime/panels/polysignal-feed', '/runtime/panels/polybeats-feed',
                  '/runtime/signals/polysignal', '/runtime/signals/polybeats']:
        response = client.get(route)
        assert response.status_code == 200
        assert response.json == payload
    assert client.get('/runtime/panels?ids=polybeats-feed').json['panels'] == {'polybeats-feed': payload}


def test_old_snapshot_preserves_clock_is_reverified_and_never_overrides_new(monkeypatch):
    old = {'items': [{'id': 'polybeats:123', 'kind': 'polybeats', 'marketId': 1}],
           'generatedAt': '2026-11-02T00:00:00Z', 'status': 'ok', 'source': 'polyData polybeats flow builder'}
    snapshots = {('snapshot:signals:polybeats', polysignal_feed_service.build_polysignal_cache_key()): old}
    resources = RuntimeResources(shutdown_timeout_seconds=.1)
    ctx = {'_resources': resources, 'get_cached_json': lambda n, k: snapshots.get((n, k)),
           'utc_now_iso': lambda: '2026-11-03T00:00:00Z', 'SIGNAL_RUNTIME_TTL_SECONDS': 300}
    seen = []
    def verify(ctx, namespace, payload):
        seen.append((namespace, deepcopy(payload)))
        return payload
    monkeypatch.setattr(signal_service, '_sanitize_signal_payload', verify)
    try:
        result = polysignal_feed_service.get_polysignal_snapshot(ctx)
        assert result['generatedAt'] == old['generatedAt'] and result['status'] == 'stale'
        assert result['items'][0]['id'] == 'polysignal:123'
        assert old['items'][0]['id'] == 'polybeats:123'
        assert seen[0][0] == 'snapshot:signals:polysignal'
        snapshots[('snapshot:signals:polysignal', polysignal_feed_service.build_polysignal_cache_key())] = {
            'items': [], 'status': 'empty', 'generatedAt': '2026-11-03T00:00:00Z'}
        assert polysignal_feed_service.get_polysignal_snapshot(ctx)['items'] == []
        assert list(resources.signal_reads) == ['snapshot:signals:polysignal']
    finally:
        resources.close()


def test_new_settings_take_precedence_and_old_settings_still_work(monkeypatch):
    monkeypatch.setenv('POLYDATA_POLYBEATS_LIMIT', '7')
    monkeypatch.delenv('POLYDATA_POLYSIGNAL_LIMIT', raising=False)
    assert polysignal_feed_service.config_value('POLYDATA_POLYSIGNAL_LIMIT', 8) == '7'
    monkeypatch.setenv('POLYDATA_POLYSIGNAL_LIMIT', '9')
    assert polysignal_feed_service.config_value('POLYDATA_POLYSIGNAL_LIMIT', 8) == '9'
