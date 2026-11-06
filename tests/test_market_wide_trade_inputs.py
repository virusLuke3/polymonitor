"""Owner key, freshness and failure semantics at the actual Agent input boundary."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from agent.market_wide.graph import _specialist_prompt, _writer_prompt
from agent.market_wide.rules import _fallback_response
from agent.market_wide.service import _build_agent_context, _normalize
from agent.market_wide.snapshot import build_market_wide_seed_payload
from api.config import load_api_settings
from api.runtime import ServiceRuntime
from api.services.signal_service import SIGNAL_SNAPSHOT_NAMESPACE_WHALES, build_whale_trades_cache_key


@pytest.mark.parametrize('stale', [False, True])
def test_runtime_reads_canonical_whale_seed_and_preserves_source_clock(tmp_path, stale):
    settings = replace(load_api_settings(), snapshot_sqlite_path=str(tmp_path / 'seed.sqlite3'))
    connection = Mock(side_effect=AssertionError('No acquisition or database calls are needed'))
    generated = (datetime.now(timezone.utc) - timedelta(hours=12 if stale else 0)).isoformat()
    # Neutral observation avoids unrelated label queries. The real owner reader,
    # namespace/key, SQLite store, read verification and TTL all remain exercised.
    row = {'id': 'whale-1', 'title': 'Neutral observation'}
    with ServiceRuntime(settings, connection_factory=connection) as runtime:
        runtime.SNAPSHOT_STORE.set(SIGNAL_SNAPSHOT_NAMESPACE_WHALES, build_whale_trades_cache_key(),
                                   {'items': [row], 'status': 'ok', 'generatedAt': generated}, 300)
        helpers = dict(runtime.agent_snapshot_context)
        helpers.update(get_active_markets_snapshot=lambda *_: {},
                       get_market_groups_payload=lambda **_: {},
                       get_latest_content_payload=lambda *_: {},
                       get_recent_trades_snapshot=lambda *_: [],
                       get_recent_oracle_snapshot=lambda *_: [],
                       get_cached_json=lambda *_: None)
        payload = build_market_wide_seed_payload(helpers, 'overview')
        state = payload['sourceStates']['whaleSignals']
        assert state['generatedAt'] == generated
        assert state['status'] == ('stale' if stale else 'ok')
        assert state['availableItemCount'] == 1
        assert state['itemCount'] == (0 if stale else 1)
        assert len(payload['whaleSignals']) == (0 if stale else 1)
        connection.assert_not_called()


@pytest.mark.parametrize('failure', [False, True])
def test_empty_and_failed_trade_reads_remain_distinct_through_model_and_output(failure):
    trades = Mock(side_effect=TimeoutError('private transport details')) if failure else Mock(return_value=[])
    payload = build_market_wide_seed_payload({'get_recent_trades_snapshot': trades}, 'overview')
    state = payload['sourceStates']['trades']
    assert state['status'] == ('error' if failure else 'empty')
    assert state['itemCount'] == 0
    assert 'private' not in str(state)
    context = _build_agent_context(payload, 'overview', [])
    assert context['metrics']['sourceStates'] == payload['sourceStates']
    for prompt in [_specialist_prompt('catalyst', 'overview', context, {}),
                   _writer_prompt('overview', context, {}, [], {})]:
        assert 'sourceStates' in prompt[1]
        assert 'never proof of no activity' in prompt[0]
    raw = {'brief': 'A sample', **{k: [] for k in ['focus', 'specialMarkets', 'themes', 'watchlist', 'evidence']}}
    for output in [_normalize(raw, payload, 'overview', [], 'test-model'),
                   _fallback_response(payload, 'overview', reason='test')]:
        assert output['sourceStates'] == payload['sourceStates']
        assert any('Recent global trades' in s for s in output['limitations']) == failure
        assert any('Whale signals are unavailable' in s for s in output['limitations'])
