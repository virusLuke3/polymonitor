"""Provider quota survives concurrent readers, restarts, UTC rollover and 429s."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
import requests

from runtime.snapshot_store import SnapshotStore
from weather import open_meteo


def test_forecast_budget_is_shared_atomic_and_honors_provider_cooldown(tmp_path, monkeypatch):
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite3'))
    store.get(open_meteo.NAMESPACE, open_meteo.KEY)
    url = 'https://api.open-meteo.com/v1/forecast'
    params = {'latitude': 1, 'longitude': 1, 'hourly': 'temperature_2m'}
    day = datetime(2026, 10, 8, 23, 50, tzinfo=timezone.utc)
    monkeypatch.setattr(open_meteo, '_now', lambda: day)
    monkeypatch.setenv('POLYDATA_OPEN_METEO_DAILY_BUDGET', '2')
    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        return {'success': True}

    def reader(_):
        try:
            # Different store instances model independently started API readers.
            return open_meteo.get_forecast(request, SnapshotStore(store.db_path), url, params=params)
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reader, range(6)))
    assert sum(value is not None for value in results) == len(calls) == 2
    assert reader(0) is None  # Restarting a reader cannot reset today's usage.
    assert len(calls) == 2

    day += timedelta(days=1)
    response = requests.Response()
    response.status_code = 429
    response._content = json.dumps({'reason': 'Daily API request limit exceeded.'}).encode()
    response.headers['Retry-After'] = '172800'

    def rate_limited(*args, **kwargs):
        raise requests.HTTPError(response=response)

    with pytest.raises(requests.HTTPError):
        open_meteo.get_forecast(rate_limited, store, url, params=params)
    day += timedelta(days=1)
    assert reader(0) is None  # A Retry-After extending past midnight is retained.
    assert len(calls) == 2
    day += timedelta(days=2)
    assert reader(0) == {'success': True}
    assert len(calls) == 3

    class MissingStore:
        db_path = str(tmp_path / 'missing' / 'budget.sqlite3')

        def get(self, *args):
            return None

    with pytest.raises(sqlite3.OperationalError):
        open_meteo.get_forecast(request, MissingStore(), url, params=params)
    assert len(calls) == 3  # Storage failures never bypass quota accounting.

    global_params = {'latitude': ','.join(['1'] * 50), 'longitude': ','.join(['1'] * 50),
        'current': ','.join(['variable'] * 5), 'hourly': ','.join(['variable'] * 6),
        'daily': ','.join(['variable'] * 7), 'forecast_days': 7}
    assert open_meteo.request_cost(global_params) == 900
    assert open_meteo.request_cost(global_params) / 10 * 24 == 2160
