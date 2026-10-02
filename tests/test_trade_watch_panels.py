from decimal import Decimal
from unittest.mock import Mock, patch

from api.services import signal_service
from api.services.trade_watch import common, flow
import unittest
import test_signals_seed_watcher as seed_helpers

NOW = '2026-10-02T09:00:00Z'


def ctx():
    return {'utc_now_iso': lambda: NOW, '_safe_decimal': lambda x: Decimal(str(x)) if x is not None else None,
            'format_trade_decimal': lambda x: str(x) if x is not None else None,
            'format_trade_address': lambda x: x, 'get_recent_oracle_events': lambda **kw: [],
            'get_recent_trades': Mock(side_effect=AssertionError('No event; no trade scan needed'))}


def fill(**changes):
    return {'marketId': 7, 'marketTitle': 'Market', 'tokenId': 'token-a', 'txHash': 'a'*64, 'logIndex': 3,
            'timestamp': '2026-10-02T08:58:00Z', 'price': '.6', 'size': '10000', 'notional': '6000',
            'side': 'SELL', 'maker': '0x'+'b'*40, 'taker': '0x'+'c'*40, **changes}


def seed(**changes):
    return {'schemaVersion': common.SCHEMA_VERSION, 'kind': 'whale-trades', 'status': 'ok',
            'generatedAt': NOW, 'items': [{**fill(), 'id': 'fill-a'}], **changes}


def test_flow_reads_fresh_explicit_seed_dependency_without_repeating_fact_scan():
    context = ctx(); context['get_cached_json'] = lambda *args: seed()
    with patch.object(common, '_query_whale_rows', side_effect=AssertionError('no duplicate scan')):
        data = flow.fetch_live_suspicious_trades_payload(context)
    assert data['status'] == 'ok' and data['sourceMode'] == 'large-trades'
    assert data['items'][0]['observationType'] == 'large-trade'
    assert data['sourceStates']['largeTrades']['mode'] == 'whale-seed'
    assert data['coverage']['oracleLinkedCount'] == 0
    context['get_recent_trades'].assert_not_called()


def test_flow_oracle_failure_is_partial_and_does_not_suppress_large_trades():
    context = ctx(); context['get_cached_json'] = lambda *args: seed()
    context['get_recent_oracle_events'] = Mock(side_effect=TimeoutError('private connection info'))
    data = flow.fetch_live_suspicious_trades_payload(context)
    assert data['status'] == 'partial' and len(data['items']) == 1
    assert data['sourceStates']['oracle']['status'] == 'error'
    assert 'private' not in data['error']


def test_flow_source_failure_is_not_a_successful_empty_assessment():
    with patch.object(common, '_query_whale_rows', side_effect=TimeoutError):
        data = flow.fetch_live_suspicious_trades_payload(ctx())
    assert data['status'] == 'degraded' and data['items'] == []
    assert data['sourceStates']['largeTrades']['status'] == 'error'


def test_overdue_seed_cannot_be_retimed_as_a_current_flow_snapshot():
    context = ctx(); context['get_cached_json'] = lambda *args: seed(generatedAt='2026-10-02T08:00:00Z')
    with patch.object(common, '_query_whale_rows', return_value=[]) as live:
        data = flow.fetch_live_suspicious_trades_payload(context)
    live.assert_called_once(); assert data['status'] == 'empty' and not data['items']


def test_oracle_window_preserves_exact_token_fill_identity_and_actual_trade_time():
    context = ctx(); context['get_cached_json'] = lambda *args: seed()
    context['get_recent_oracle_events'] = lambda **kw: [{'marketId': '7', 'eventTime': '2026-10-02T08:59:00Z'}]
    context['get_recent_trades'] = lambda **kw: [fill(), fill(logIndex=4, tokenId='token-b'), fill(logIndex=5, timestamp='2026-10-02T08:59:30Z')]
    with patch.object(flow.outcome_semantics_service, 'annotate_raw_trade_rows', side_effect=lambda c, rows: rows):
        data = flow.fetch_live_suspicious_trades_payload(context)
    linked = [item for item in data['items'] if item['observationType'] == 'oracle-linked']
    assert len(linked) == 2 and {item['tokenId'] for item in linked} == {'token-a', 'token-b'}
    assert len({item['id'] for item in linked}) == 2
    assert all(item['side'] == 'SELL' and item['timestamp'] == '2026-10-02T08:58:00Z' for item in linked)


def test_whale_candidates_are_oversampled_once():
    with patch.object(common.clickhouse_orderfilled_service, 'get_volume_whale_rows', return_value=[]) as query:
        signal_service.fetch_live_whale_trades_payload(ctx(), limit=14)
    assert query.call_args.kwargs['limit'] == 28


class TradeWatcherDiagnosticsTest(unittest.TestCase):
    make_watcher = seed_helpers.SignalsSeedWatcherTestCase.make_watcher
    def test_failed_refresh_preserves_success_time_and_exposes_attempt_and_safe_diagnostics(self):
        watcher, redis = self.make_watcher()
        previous = seed(); watcher.store_payload(previous)
        with patch.object(watcher, 'fetch_payload', side_effect=TimeoutError('secret connection')):
            watcher.run_once()
        import json
        data = json.loads(redis.get(watcher.redis_key()))
        assert data['generatedAt'] == NOW and data['items'] == previous['items']
        assert data['status'] == 'stale' and data['lastAttemptAt']
        assert data['errorCode'] == 'trade-source-refresh-failed' and 'secret' not in data['error']
