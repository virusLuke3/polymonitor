"""One durable guest allowance even when research and serving stores differ."""
from datetime import datetime, timezone

from data_sources import source_value
from runtime.snapshot_store import SnapshotStore

NAMESPACE = 'research:esports:anonymous-odds:v1'


def reserve_guest(default_store):
    path = source_value('POLYDATA_BOOKMAKER_QUOTA_SQLITE_PATH')
    store = SnapshotStore(path) if path else default_store
    key = 'quota:oddslink:' + datetime.now(timezone.utc).date().isoformat()
    with store.fetch_lock(NAMESPACE, 'guest-budget', timeout=1):
        attempts = (store.get_stale(NAMESPACE, key) or {}).get('attempts', 0)
        if attempts >= 5:
            return False
        if not store.set(NAMESPACE, key, {'attempts': attempts + 1}, 86400, max_entries=16):
            raise RuntimeError('Guest budget was not saved')
    return True
