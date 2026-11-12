"""Restartable matching worker. Odds and catalog are reused; rule documents refresh daily."""
import json
import os
import signal
import threading

from runtime.environment import load_environment
from runtime.redis_snapshot_store import create_snapshot_store
from api.config import load_api_settings
from api.services.bookmaker_panels.settlement import collect_rules
from api.services.bookmaker_panels.match_store import MatchStore
from api.services.bookmaker_panels.match_owner import Catalog, NAMESPACE, run_cycle
from api.services.bookmaker_panels.movi_archive import configured_int


def main():
    load_environment()
    store = create_snapshot_store(os.environ['POLYDATA_SNAPSHOT_SQLITE_PATH'])
    archive = MatchStore()
    archive.initialize()
    catalog = Catalog(load_api_settings())
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    interval = configured_int('POLYDATA_ODDS_MATCH_INTERVAL_SECONDS', 60, 30, 3600)
    with store.fetch_lock(NAMESPACE, 'owner', timeout=0):
        while not stopping.is_set():
            try:
                collect_rules(store)
                print(json.dumps({'owner': 'bookmaker-matching', **run_cycle(store, archive, catalog)}), flush=True)
            except Exception as exc:
                collect_rules(store)
                print(json.dumps({'owner': 'bookmaker-matching', 'error': type(exc).__name__}), flush=True)
            stopping.wait(interval)


if __name__ == '__main__':
    main()
