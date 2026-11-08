"""One scheduled process per evidence family; per-source clocks prevent overfetch."""
from __future__ import annotations
import argparse
import json
import os
from importlib import import_module
from runtime.environment import load_environment
from runtime.snapshot_store import SnapshotStore

OWNERS = {
    'geopolitics': 'geopolitics_expansion',
    'weather': 'weather_expansion',
    'sports': 'sports_expansion.snapshot_service',
    'finance': 'finance_expansion',
    'culture-tech': 'culture_tech',
}


def main():
    load_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner', required=True, choices=OWNERS)
    args = parser.parse_args()
    store = SnapshotStore(os.environ['POLYDATA_SNAPSHOT_SQLITE_PATH'])
    try:
        result = import_module('api.services.'+OWNERS[args.owner]).collect(store)
    except TimeoutError:
        result = {'acquisition': 'deferred-lock'}
    from api.services.external_panels_service import publish_health
    publish_health(store, OWNERS[args.owner])
    print(json.dumps({'owner': args.owner, 'sources': result}), flush=True)


if __name__ == '__main__':
    main()
