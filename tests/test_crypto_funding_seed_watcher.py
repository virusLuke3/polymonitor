from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api.services import crypto_funding_service
from runtime import crypto_funding_watcher
from runtime.snapshot_store import SnapshotStore

NOW = '2026-10-04T10:00:00Z'


class FakeRedis:
    def __init__(self): self.values = {}
    def ping(self): return True
    def get(self, key): return self.values.get(key)
    def set(self, key, value, ex=None): self.values[key] = value


def settings(path=''):
    return SimpleNamespace(redis_url='redis://test/0', redis_prefix='polydata:', snapshot_sqlite_path=path,
        crypto_funding_watch_api_url='https://binance.test/fapi/v1/premiumIndex',
        crypto_funding_watch_bybit_api_url='https://bybit.test/v5/market/tickers',
        crypto_funding_watch_ttl_seconds=15, crypto_funding_watch_symbols=('BTCUSDT',))


def sample_payload():
    quote = {'id': 'binance:BTCUSDT', 'asset': 'BTC', 'exchange': 'Binance', 'symbol': 'BTCUSDT',
        'fundingRate': -0.0004, 'fundingRatePercent': -0.04, 'fundingRatePercent8h': -0.04,
        'fundingIntervalHours': 8, 'updatedAt': NOW, 'eligibilityCheckedAt': NOW, 'eligible': True,
        'acquisitionState': 'ok', 'fetchedAt': NOW, 'quoteObservedAt': NOW, 'sourceResponseAt': None}
    return {'schemaVersion': 3, 'kind': 'crypto-funding', 'generatedAt': NOW, 'lastSuccessAt': NOW,
        'status': 'ok', 'sources': {'binance': 'ok', 'bybit': 'ok'}, 'venues': ['Binance'],
        'assets': [{'id': 'BTC', 'asset': 'BTC', 'quotes': [quote]}], 'items': [quote],
        'coverage': {'succeeded': 1, 'retained': 0, 'missing': 0, 'expectedQuotes': 1}}


class CryptoFundingSeedWatcherTestCase(unittest.TestCase):
    def make_watcher(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = settings(str(Path(directory.name) / 'snapshots.sqlite3'))
        fake = FakeRedis()
        with patch.object(crypto_funding_watcher, 'redis', SimpleNamespace(from_url=lambda *args, **kwargs: fake)):
            watcher = crypto_funding_watcher.CryptoFundingWatcher(redis_url=config.redis_url, redis_prefix=config.redis_prefix,
                snapshot_sqlite_path=config.snapshot_sqlite_path, settings=config, interval_seconds=30)
        self.addCleanup(watcher.close)
        return watcher, fake

    def test_watcher_publishes_seed_and_logs_only_a_summary(self):
        watcher, fake = self.make_watcher()
        with patch.object(crypto_funding_service, 'fetch_live_crypto_funding_watch_payload', return_value=sample_payload()):
            result = watcher.run_once()
        self.assertEqual('ok', result['status'])
        self.assertNotIn('payload', result)
        stored = json.loads(fake.get(watcher.redis_key()))
        self.assertEqual(30, stored['refreshIntervalSeconds'])
        self.assertEqual(NOW, stored['generatedAt'])
        meta = json.loads(fake.get('polydata:seed-meta:crypto:funding-watch'))
        self.assertEqual('ok', meta['status'])
        self.assertIsNotNone(meta['lastSuccessAt'])

    def test_first_failure_does_not_manufacture_a_success_time(self):
        watcher, fake = self.make_watcher()
        with patch.object(crypto_funding_service, 'fetch_live_crypto_funding_watch_payload', side_effect=TimeoutError()):
            result = watcher.run_once()
        self.assertEqual('unavailable', result['status'])
        meta = json.loads(fake.get('polydata:seed-meta:crypto:funding-watch'))
        self.assertIsNone(meta['lastSuccessAt'])

    def test_failure_preserves_values_but_never_resets_source_clocks(self):
        watcher, fake = self.make_watcher()
        with patch.object(crypto_funding_service, 'fetch_live_crypto_funding_watch_payload', return_value=sample_payload()):
            watcher.run_once()
        before_meta = json.loads(fake.get('polydata:seed-meta:crypto:funding-watch'))
        with patch.object(crypto_funding_service, 'fetch_live_crypto_funding_watch_payload', side_effect=TimeoutError()):
            watcher.run_once()
        stored = json.loads(fake.get(watcher.redis_key()))
        self.assertEqual('stale', stored['status'])
        self.assertEqual(NOW, stored['generatedAt'])
        self.assertEqual(NOW, stored['items'][0]['updatedAt'])
        self.assertEqual('retained', stored['assets'][0]['quotes'][0]['acquisitionState'])
        self.assertEqual(-0.04, stored['items'][0]['fundingRatePercent'])
        after_meta = json.loads(fake.get('polydata:seed-meta:crypto:funding-watch'))
        self.assertEqual(before_meta['lastSuccessAt'], after_meta['lastSuccessAt'])

    def test_sqlite_fallback_serves_the_canonical_seed_without_collecting_or_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            config = settings(str(Path(directory) / 'snapshots.sqlite3'))
            store = SnapshotStore(config.snapshot_sqlite_path)
            key = crypto_funding_service.build_crypto_funding_cache_key(config)
            store.set(crypto_funding_service.CRYPTO_FUNDING_NAMESPACE, key, sample_payload(), 60)
            get = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('external call'))
            ctx = {'SETTINGS': config, 'SNAPSHOT_STORE': store, 'get_cached_json': lambda *args: None,
                   'http_json_get': get, 'utc_now_iso': lambda: NOW}
            with patch.object(store, 'set', side_effect=AssertionError('serving wrote sqlite')):
                payload = crypto_funding_service.get_crypto_funding_watch_snapshot(ctx)
            self.assertEqual('ok', payload['status'])
            self.assertEqual('BTC', payload['assets'][0]['asset'])

    def test_view_limits_share_one_acquisition_identity_and_trim_flat_quotes(self):
        watcher, fake = self.make_watcher()
        payload = sample_payload()
        payload['assets'].append({'id': 'ETH', 'asset': 'ETH', 'quotes': [{'id': 'binance:ETHUSDT'}]})
        payload['items'].append({'id': 'binance:ETHUSDT', 'asset': 'ETH'})
        watcher.store_payload(payload)
        self.assertEqual(crypto_funding_service.build_crypto_funding_cache_key(watcher.settings, limit=1),
                         crypto_funding_service.build_crypto_funding_cache_key(watcher.settings, limit=120))
        ctx = watcher.service_context(); ctx['utc_now_iso'] = lambda: NOW
        small = crypto_funding_service.get_crypto_funding_watch_snapshot(ctx, limit=1)
        self.assertEqual(1, len(small['assets']))
        self.assertEqual(['BTC'], [row['asset'] for row in small['items']])
