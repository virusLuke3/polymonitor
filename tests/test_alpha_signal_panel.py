from copy import deepcopy
from unittest.mock import patch
from api.context import RuntimeResources
from api.config import ClickHouseSettings
from api.services import alpha_signal_service as alpha, outcome_semantics_service as semantics
from test_outcome_semantics_service import _rows


def context(labels=('Yes', 'No'), directional=False, yes_no=True):
    projected = _rows('up_down_labels' if directional else 'yes_no_labels' if yes_no else 'source_first_second', labels,
                      directional=directional, yes_no=yes_no, tokens=('token-a', 'token-b'))
    return {'_resources': RuntimeResources(clickhouse=ClickHouseSettings()),
            'get_backend': lambda: 'postgres', 'query_all': lambda sql, params=(): projected if 'registry_token_id' in sql else [],
            'utc_now_iso': lambda: '2026-10-02T09:00:00Z'}


def row(**changes):
    return {'market_id': 7, 'token_id': 'token-a', 'market_title': 'Verified market', 'side': 'BUY',
            'price': '.62', 'flow_notional': 15000, 'net_flow_notional': 14000, 'net_direction_strength': .875,
            'max_trade_notional': 8000, 'market_share': .3, 'unique_trader_count': 6, 'trade_count': 12,
            'timestamp': '2026-10-02T08:59:50Z', 'source_observed_at': '2026-10-02T08:59:58Z', **changes}


def build(ctx, rows):
    with patch.object(alpha, '_candidates', return_value=rows):
        return alpha.fetch_live_alpha_signal_payload(ctx)


def test_token_identity_does_not_depend_on_stored_outcome_code_or_mutation_receipt():
    result = build(context(), [row()])
    assert result['status'] == 'ok'
    item = result['items'][0]
    assert item['logicalOutcome'] == 'YES' and item['outcome'] == 'Yes'
    assert item['tokenId'] == 'token-a' and item['metrics']['uniqueTraderCount'] == 6
    assert item['metrics']['score'] <= 100
    assert result['coverage']['verifiedCount'] == 1
    # Legacy tokenless aggregates remain gated by mutation proofs.
    assert semantics.project_aggregate_directional_rows(context(), [{'market_id': 7, 'outcome': 'YES', 'price': '.62', 'block_number': 123}]) == []


def test_wrong_token_or_logical_alias_is_rejected_with_denominators():
    result = build(context(), [row(token_id='foreign-token'), row(logicalOutcome='NO')])
    assert result['status'] == 'degraded'
    assert result['items'] == [] and result['coverage']['candidateCount'] == 2
    assert result['coverage']['rejectedCount'] == 2
    assert result['coverage']['rejectionReasons']['trade_token_projection_mismatch'] == 1


def test_up_down_and_sell_direction_are_projected_from_real_token():
    result = build(context(('Up', 'Down'), directional=True, yes_no=False), [row(token_id='token-b', side='SELL')])
    assert result['items'][0]['outcome'] == 'Down'
    assert result['items'][0]['side'] == 'SELL'
    assert 'bias' not in result['items'][0]


def test_unsupported_source_labels_are_not_directional_alpha():
    result = build(context(('Alice', 'Bob'), yes_no=False), [row()])
    assert result['status'] == 'degraded' and result['items'] == []


def test_empty_failure_partial_and_stale_source_are_distinct():
    assert build(context(), [])['status'] == 'empty'
    assert build(context(), None)['status'] == 'degraded'
    mixed = build(context(), [row(), row(token_id='foreign-token')])
    assert mixed['status'] == 'partial' and len(mixed['items']) == 1
    old = build(context(), [row(source_observed_at='2026-10-02T08:00:00Z')])
    assert old['status'] == 'stale' and len(old['items']) == 1
    invalid = build(context(), [row(price='nan')])
    assert invalid['status'] == 'degraded' and invalid['items'] == []


def test_stable_ids_market_dedup_and_current_public_revalidation():
    ctx = context(); result = build(ctx, [row(), row(token_id='token-b')])
    assert len(result['items']) == 1
    assert result['items'][0]['id'] == build(ctx, [row()])['items'][0]['id']
    public = semantics.sanitize_public_market_payload(ctx, deepcopy(result))
    assert public['items'][0]['logicalOutcome'] == 'YES'
    assert public['items'][0]['priceProjectionValid'] is True
    assert public['items'][0]['metrics']['uniqueTraderCount'] == 6


def test_query_keeps_exact_tokens_and_never_infers_outcome_codes():
    with patch.object(alpha.trades, '_query_json_rows', side_effect=[[{'watermark': 12345}], []]) as query:
        assert alpha._candidates(context(), 8) == []
    sql = query.call_args.args[1]
    assert 'outcome_code' not in sql
    assert 'GROUP BY market_id, token_id' in sql and 'LIMIT 96' in sql


def test_missing_labels_allow_only_canonical_neutral_observations():
    ctx = context()
    def reader(sql, params=()):
        if 'registry_token_id' in sql:
            return [{'market_id': 7, 'registry_token_id': 'token-a', 'label_token_id': None}]
        if 'yes_token_id, no_token_id' in sql:
            return [{'id': 7, 'yes_token_id': 'token-a', 'no_token_id': 'token-b'}]
        return []
    ctx['query_all'] = reader
    result = build(ctx, [row()])
    assert result['status'] == 'partial' and result['items'] == []
    observation = result['candidates'][0]
    assert observation['marketIdentityVerified'] is True
    assert 'outcome' not in observation and 'price' not in observation and 'score' not in observation['metrics']
    assert build(ctx, [row(token_id='foreign-token')])['candidates'] == []
    public = semantics.sanitize_public_market_payload(ctx, deepcopy(result))
    assert public['candidates'][0]['outcomeSemanticsValid'] is False
    assert public['candidates'][0]['metrics']['netFlowNotional'] == 14000


def test_cached_observations_recheck_current_ownership_and_reject_malformed_identity():
    ctx = context(); ctx['query_all'] = lambda sql, params=(): [{'id': 7, 'yes_token_id': 'token-a', 'no_token_id': 'token-b'}]
    candidate = {'id': 'candidate', 'marketId': 7, 'tokenId': 'token-a', 'qualification': 'labels-unavailable'}
    data = {'items': [], 'candidates': [candidate], 'status': 'partial'}
    assert alpha.revalidate_cached_observations(ctx, data)['candidates'] == [candidate]
    ctx['query_all'] = lambda sql, params=(): []
    result = alpha.revalidate_cached_observations(ctx, data)
    assert result['status'] == 'degraded' and result['candidates'] == []
    assert alpha.revalidate_cached_observations(ctx, {**data, 'candidates': [{**candidate, 'marketId': 'bad'}]})['candidates'] == []


def test_invalid_cached_alpha_is_not_reclassified_as_healthy_empty():
    from api.services import signal_service
    ctx = context(); data = build(ctx, [row()])
    ctx['query_all'] = lambda sql, params=(): []
    result = signal_service._sanitize_signal_payload(ctx, signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA, data)
    assert result['items'] == [] and result['status'] == 'degraded'
    assert result['coverage']['lastReadRejectedCount'] == 1
