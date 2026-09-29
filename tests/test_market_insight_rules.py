from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from agent.market_wide.rules import _fallback_response, _summary_metrics
from agent.market_wide.service import _normalize
from agent.market_wide.snapshot import build_market_wide_snapshot


def market(**values):
    return {'id': 1, 'title': 'Market A', 'category': 'sports', **values}


def test_volume_and_category_counts_cannot_manufacture_anomalies_or_rotation():
    payload = {'markets': [market(volume24h=10_000_000)], 'marketGroups': [{'eventId': 'g', 'title': 'Large event', 'volume24h': 100_000_000}]}
    special = _fallback_response(payload, 'special', reason='gateway-error')
    trend = _fallback_response(payload, 'trend', reason='gateway-error')
    assert special['specialMarkets'] == []
    assert trend['themes'] == []
    assert 'rotating' not in trend['brief']
    assert special['generationMode'] == 'rules'
    assert special['status'] == 'gateway-error'


def test_reported_price_comparisons_preserve_zero_and_do_not_invent_missing_history():
    payload = {'markets': [market(latestPrice=.1, price24hAgo=0), market(id=2, title='Unknown history', latestPrice=.8)]}
    trend = _fallback_response(payload, 'trend', reason='gateway-error')
    assert len(trend['themes']) == 1
    assert trend['themes'][0]['evidence'] == '+10.0 pp / 24h'
    assert 'persistent trend' in trend['themes'][0]['summary']
    special = _fallback_response(payload, 'special', reason='gateway-error')
    assert len(special['specialMarkets']) == 1
    assert special['specialMarkets'][0]['marketId'] == 1


def test_sample_counts_deduplicate_market_identity_and_do_not_sum_event_turnover():
    row = market(volume24h=1000)
    metrics = _summary_metrics({'markets': [row, row], 'marketGroups': [{'eventId': 'g', 'volume24h': 1000}]})
    assert metrics['activeMarkets'] == metrics['coveredMarkets'] == 1
    assert metrics['marketGroups'] == 1
    assert metrics['visible24hVolume'] == '$1.0K'
    assert metrics['coverageScope'] == 'sample'


def test_valid_ai_empty_results_stay_empty_and_malformed_output_is_not_ai():
    raw = {'brief': 'No supported signal.', 'focus': [], 'specialMarkets': [], 'themes': [], 'watchlist': [], 'evidence': []}
    payload = {'markets': [market(latestPrice=.5, volume24h=50000)]}
    result = _normalize(raw, payload, 'special', [], 'model')
    assert result['status'] == 'live'
    assert result['generationMode'] == 'ai'
    assert result['specialMarkets'] == result['focus'] == []
    invalid = _normalize({'brief': 'Unsupported'}, payload, 'special', [], 'model')
    assert invalid['generationMode'] == 'rules'
    assert invalid['status'] == 'invalid-agent-output'


def test_failed_snapshot_can_retry_without_waiting_twelve_hours():
    old = {'generatedAt': (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(), 'data': {'status': 'gateway-error'}}
    with patch('agent.market_wide.snapshot.read_market_wide_snapshot', return_value=old), \
         patch('agent.market_wide.snapshot._seed_live_enabled', return_value=True), \
         patch('agent.market_wide.snapshot.build_market_wide_seed_payload', return_value={'lens': 'overview'}), \
         patch('agent.market_wide.snapshot.gateway_configured', return_value=True), \
         patch('agent.market_wide.snapshot.call_market_wide_insight_gateway', return_value={'status': 'live', 'brief': 'Recovered'}) as gateway:
        result = build_market_wide_snapshot({}, 'overview')
    gateway.assert_called_once()
    assert result['data']['status'] == 'live'


def test_unknown_trade_counts_are_not_zero_trade_anomalies():
    from agent.market_wide.graph import _build_quant_forecaster
    result = _build_quant_forecaster({'markets': [market(latestPrice=.2, volume24h=200_000, tradeCount24h=None)]})
    assert result['topFlowMarkets'][0]['tradeCount24h'] is None
    assert not any(row['type'] == 'volume-without-trade-count' for row in result['anomalies'])


def test_stale_fill_tape_cannot_be_described_as_fresher_price_evidence():
    from agent.market_wide.graph import _fill_tape_microstructure
    rows = _fill_tape_microstructure({'topMarketFillTape': [{'title': 'Old fills', 'latestFillYesPrice': .5, 'fillCountLoaded': 10, 'fillFreshness': 'stale-fills'}]})
    assert 'cannot anchor current' in rows[0]['interpretation']
