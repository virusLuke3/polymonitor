from unittest.mock import Mock

import pytest

from agent.market_wide import snapshot
from runtime.snapshot_store import SnapshotStore


@pytest.mark.parametrize('reader,namespace,key', [
    (snapshot.read_market_wide_snapshot, snapshot.SNAPSHOT_NAMESPACE, snapshot.snapshot_cache_key('overview')),
    (snapshot.read_market_wide_quant_snapshot, snapshot.QUANT_SNAPSHOT_NAMESPACE, snapshot.quant_snapshot_cache_key('overview')),
])
def test_new_local_publication_is_not_hidden_by_older_redis_entry(tmp_path, reader, namespace, key):
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite'))
    older = {'generatedAt': '2026-11-10T00:00:00Z', 'data': {'status': 'live'}}
    current = {'generatedAt': '2026-11-10T08:00:00Z', 'data': {'status': 'live'}, 'expiresAt': '2026-11-10T20:00:00Z'}
    redis = Mock(return_value=older)
    helpers = {'SNAPSHOT_STORE': store, 'get_cached_json': redis}
    assert reader(helpers, 'overview') == older
    redis.reset_mock()
    store.set(namespace, key, current, 43200)
    assert reader(helpers, 'overview') == current
    redis.assert_not_called()
