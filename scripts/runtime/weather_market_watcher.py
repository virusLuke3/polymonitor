#!/usr/bin/env python3
"""Shared weather catalog (5 min) and official display books (30 sec demand)."""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.clients.source_transport import SourceSession
from api.config import load_api_settings
from api.services import global_weather_map_service as weather
from api.services import weather_market_service as market
from data_sources import source_value
from runtime.environment import load_environment
from runtime.global_weather_map_watcher import GlobalWeatherMapWatcher
from weather.cities import load_weather_cities


class WeatherMarketWatcher(GlobalWeatherMapWatcher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.books_session = SourceSession()
        self.books_session.trust_env = False
        self.catalog_interval = market.setting("POLYMONITOR_WEATHER_CATALOG_INTERVAL_SECONDS", 300, 60)
        self.book_interval = market.setting("POLYMONITOR_WEATHER_BOOK_INTERVAL_SECONDS", 30, 15)
        self.timeout = market.setting("POLYMONITOR_WEATHER_BOOK_TIMEOUT_SECONDS", 12, 2, 45)
        self.round_seconds = market.setting("POLYMONITOR_WEATHER_BOOK_ROUND_SECONDS", 90, 24, 120)

    def close(self):
        self.books_session.close()
        super().close()

    def collect_catalog(self):
        started = time.time()
        previous = self.snapshot_store.get_stale(market.NAMESPACE, market.CATALOG_KEY) or {}
        ctx = self.context()
        cities = load_weather_cities(limit=60)
        dates = weather._date_labels(weather._dependencies(ctx), int(getattr(self.settings, 'global_weather_market_days', 4) or 4))
        rows, statuses = weather._db_markets_by_city(ctx, cities, dates, query_books=False)
        if any(s == 'error' for s in statuses.values()):
            payload = {**previous, 'status': 'error', 'lastAttemptAt': market.iso(started), 'error': 'catalog-read-failed'}
        else:
            stamp = market.iso()
            items = [{**rows.get(str(city['city_id']), {}), 'cityId': str(city['city_id']),
                      'city': city['city'], 'timezone': city.get('timezone') or 'UTC',
                      'marketFetchedAt': stamp} for city in cities]
            payload = {'schemaVersion': 1, 'status': 'ok', 'generatedAt': stamp,
                       'lastAttemptAt': market.iso(started), 'items': items}
        market.publish(self.snapshot_store, market.CATALOG_KEY, payload)
        return {'kind': 'catalog', 'status': payload['status'], 'generatedAt': payload.get('generatedAt'),
                'tokens': len(market.catalog_tokens(market.read_catalog(self.snapshot_store)))}

    def collect_books(self, *, overview=False):
        started = time.time()
        deadline = time.monotonic() + self.round_seconds
        catalog = market.read_catalog(self.snapshot_store)
        allowed = market.catalog_tokens(catalog)
        saved = self.snapshot_store.get_stale(market.NAMESPACE, market.BOOKS_KEY) or {}
        books = {t: b for t, b in saved.get('books', {}).items() if t in allowed}
        active = set()
        for city in catalog.get('items', []):
            lease = self.snapshot_store.get(market.STATE, 'demand:' + city['cityId']) or {}
            active.update(t for t, until in lease.get('tokens', {}).items() if until > started and t in allowed)
        primary = {str(row['yesTokenId']) for city in catalog.get('items', []) for row in city.get('bins', []) if row.get('yesTokenId')}
        tokens = sorted(active) + sorted(primary - active) if overview else sorted(active)
        success, errors = 0, {}
        base = source_value('POLYDATA_CLOB_API_BASE').rstrip('/')
        if not base:
            errors['source'] = 'not-configured'
            tokens = []
        for offset in range(0, len(tokens), 100):
            batch = tokens[offset:offset + 100]
            if time.monotonic() + self.timeout > deadline:
                errors.update({token: 'round-budget' for token in tokens[offset:]})
                break
            try:
                raw = self.books_session.read_weather_books(base + '/books', batch, timeout=self.timeout,
                                                           source_deadline=deadline)
                if not isinstance(raw, list) or len(raw) > len(batch):
                    raise ValueError('invalid batch response')
                by_token = {}
                for row in raw:
                    token = row.get('asset_id') if isinstance(row, dict) else None
                    if token not in batch or token in by_token:
                        raise ValueError('unexpected or duplicate token')
                    by_token[token] = row
                received = time.time()
                for token in batch:
                    try:
                        books[token] = market.validate_book(by_token.get(token), token, received,
                                                           max(90, self.book_interval * 3) if token in active else self.catalog_interval * 2)
                        success += 1
                    except (ValueError, KeyError, TypeError, OverflowError):
                        errors[token] = 'missing-or-invalid-book'
            except Exception as exc:
                # Errors never include credential-bearing proxy addresses.
                errors.update({token: type(exc).__name__ for token in batch})
                if getattr(getattr(exc, 'response', None), 'status_code', None) in {403, 429}:
                    errors.update({token: 'source-backoff' for token in tokens[offset + 100:]})
                    break
        for token, error in errors.items():
            if token in books:
                books[token] = {**books[token], 'bookStatus': 'stale', 'upstreamReady': False, 'error': error}
        payload = {'schemaVersion': 1, 'books': books, 'errors': errors, 'lastAttemptAt': market.iso(started),
                   'lastSuccessAt': market.iso() if success else saved.get('lastSuccessAt'),
                   'requested': len(tokens), 'received': success, 'catalogAt': catalog.get('generatedAt')}
        market.publish(self.snapshot_store, market.BOOKS_KEY, payload)
        return {'kind': 'books', 'requested': len(tokens), 'received': success, 'failed': len(errors),
                'catalogRefreshNeeded': 'missing-or-invalid-book' in errors.values(),
                'lastSuccessAt': payload['lastSuccessAt']}

    def watch(self):
        # Independent catalog slot: DB delays cannot block selected-city books.
        next_catalog = next_books = next_overview = 0.0
        last_catalog = -self.catalog_interval
        catalog_future = None
        with ThreadPoolExecutor(max_workers=1) as pool:
            while True:
                now = time.monotonic()
                if catalog_future is not None and catalog_future.done():
                    try:
                        print(json.dumps(catalog_future.result()), flush=True)
                    except Exception as exc:
                        print(json.dumps({'kind': 'catalog', 'error': type(exc).__name__}), flush=True)
                    catalog_future = None
                if catalog_future is None and now >= next_catalog:
                    catalog_future = pool.submit(self.collect_catalog)
                    last_catalog = now
                    next_catalog = now + self.catalog_interval
                if now >= next_books:
                    overview = now >= next_overview
                    try:
                        result = self.collect_books(overview=overview)
                        print(json.dumps(result), flush=True)
                        if result.get('catalogRefreshNeeded'):
                            next_catalog = min(next_catalog, max(now, last_catalog + 60))
                        if overview and result['requested']:
                            next_overview = now + self.catalog_interval
                    except Exception as exc:
                        print(json.dumps({'kind': 'books', 'error': type(exc).__name__}), flush=True)
                    next_books = now + self.book_interval
                time.sleep(1)


def main():
    load_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    settings = load_api_settings()
    owner = WeatherMarketWatcher(redis_url=settings.redis_url, redis_prefix=settings.redis_prefix,
                                 snapshot_sqlite_path=settings.snapshot_sqlite_path, settings=settings, interval_seconds=300)
    try:
        lock_path = Path(owner.snapshot_store.db_path + '.weather-markets.lock')
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.watch:
                owner.watch()
            else:
                print(json.dumps(owner.collect_catalog()))
                print(json.dumps(owner.collect_books(overview=True)))
    finally:
        owner.close()


if __name__ == '__main__':
    main()
