"""Deterministic, sample-scoped observations used when generation is unavailable."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from agent.common.json_utils import compact_text


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _number(value: Any) -> float | None:
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    return _number(value) or 0.0


def _fmt_compact(value: Any) -> str:
    number = _as_float(value)
    if abs(number) >= 1_000_000:
        return f'{number / 1_000_000:.1f}M'
    if abs(number) >= 1_000:
        return f'{number / 1_000:.1f}K'
    return f'{number:g}'


def _fmt_currency(value: Any) -> str:
    return f'${_fmt_compact(value)}'


def _items(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _signal_items(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return _items(value, 'items') if isinstance(value, dict) else _items(payload, key)


def _market_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key, kind in [('markets', 'market'), ('marketGroups', 'group')]:
        for item in _items(payload, key):
            if not isinstance(item, dict):
                continue
            identity = (item.get('conditionId') or item.get('id') or item.get('localMarketId')) if kind == 'market' else (item.get('eventId') or item.get('groupId') or item.get('slug'))
            identity = str(identity or item.get('title') or '')
            if not identity or (kind, identity) in seen:
                continue
            seen.add((kind, identity))
            candidate = {**item, 'kind': kind, 'title': item.get('title') or item.get('slug') or 'Untitled market'}
            if kind == 'group':
                outcomes = item.get('topOutcomes') or item.get('outcomes') or []
                candidate['outcomes'] = [outcome for outcome in outcomes if isinstance(outcome, dict)][:4]
                # An event has multiple prices; do not assign one child's price to the event.
                candidate['latestPrice'] = None
            candidates.append(candidate)
    return candidates


def _top_categories(markets: list[Any]) -> list[str]:
    counts: dict[str, int] = {}
    for item in markets:
        if isinstance(item, dict):
            category = str(item.get('category') or 'unclassified').strip().lower()
            counts[category] = counts.get(category, 0) + 1
    return [f'{name} {count}' for name, count in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:4]]


def _summary_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = _market_candidates(payload)
    markets = [item for item in candidates if item['kind'] == 'market']
    groups = [item for item in candidates if item['kind'] == 'group']
    return {
        'activeMarkets': len(markets), 'marketGroups': len(groups),
        'coveredMarkets': len(markets), 'coverageScope': 'sample',
        'topCategories': _top_categories(markets),
        'visible24hVolume': _fmt_currency(sum(_as_float(item.get('volume24h')) for item in markets)),
        'tradeRows': len(_items(payload, 'trades')), 'oracleEvents': len(_items(payload, 'oracle')),
        'contentItems': len(_items(payload, 'content')), 'fillTapeMarkets': len(_items(payload, 'topMarketFillTape')),
        'fillTapeConflicts': sum(bool(item.get('priceSourceConflict')) for item in _items(payload, 'topMarketFillTape') if isinstance(item, dict)),
        **{key: len(_signal_items(payload, key)) for key in ('whaleSignals', 'suspiciousSignals', 'alphaSignals')},
    }


def _price_change(candidate: dict[str, Any]) -> tuple[float, float, float] | None:
    current, prior = _number(candidate.get('latestPrice')), _number(candidate.get('price24hAgo'))
    if current is None or prior is None or not (0 <= current <= 1 and 0 <= prior <= 1):
        return None
    return current, prior, (current - prior) * 100


def _special_markets(payload: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    observations = []
    for item in _market_candidates(payload):
        if item['kind'] != 'market':
            continue
        change = _price_change(item)
        price = _number(item.get('latestPrice'))
        if change and abs(change[2]) >= 5:
            trend, evidence = '24h probability move', f'{change[1] * 100:.1f}% → {change[0] * 100:.1f}% ({change[2]:+.1f} pp)'
            why = 'Reported 24h price comparison. Check source freshness and catalysts before interpreting the move.'
            rank = (2, abs(change[2]))
        elif price is not None and 0.42 <= price <= 0.58:
            trend, evidence = 'Balanced odds', f'{price * 100:.1f}%'
            why = 'Current price is near 50%. This describes pricing uncertainty, not an unusual volume change.'
            rank = (1, _as_float(item.get('volume24h')))
        else:
            continue
        observations.append((rank, {
            'title': compact_text(item['title'], 120), 'marketId': item.get('id') or item.get('localMarketId'),
            'why': why, 'trend': trend, 'severity': 'neutral', 'evidence': evidence,
        }))
    return [item for _, item in sorted(observations, key=lambda pair: pair[0], reverse=True)[:limit]]


def _trend_themes(payload: dict[str, Any]) -> list[dict[str, str]]:
    changes = [(item, _price_change(item)) for item in _market_candidates(payload) if item['kind'] == 'market']
    measured = [(item, change) for item, change in changes if change is not None and abs(change[2]) >= 1]
    return [{
        'label': '24H CHANGE', 'title': compact_text(item['title'], 120),
        'summary': f'Reported probability moved from {prior * 100:.1f}% to {current * 100:.1f}% over 24h. One interval does not establish a persistent trend.',
        'severity': 'neutral', 'evidence': f'{delta:+.1f} pp / 24h',
    } for item, (current, prior, delta) in sorted(measured, key=lambda pair: abs(pair[1][2]), reverse=True)[:4]]


def _fallback_response(payload: dict[str, Any], lens: str, *, reason: str, search_results: list[dict[str, str]] | None = None) -> dict[str, Any]:
    metrics = _summary_metrics(payload)
    special = _special_markets(payload)
    themes = _trend_themes(payload) if lens == 'trend' else []
    focus = []
    if lens == 'overview':
        markets = [item for item in _market_candidates(payload) if item['kind'] == 'market']
        ranked = sorted(markets, key=lambda item: _as_float(item.get('volume24h')), reverse=True)[:3]
        for item in ranked:
            price = _number(item.get('latestPrice'))
            focus.append({'label': 'SAMPLE', 'title': compact_text(item['title'], 120),
                          'summary': 'Among the highest reported 24h volumes in this market sample. No historical volume baseline is available.',
                          'severity': 'neutral', 'evidence': f"{_fmt_currency(item.get('volume24h'))} reported / 24h" + (f' · {price * 100:.1f}%' if price is not None and 0 <= price <= 1 else '')})
        brief = f"Rules-based overview of {metrics['activeMarkets']} sampled markets and {metrics['marketGroups']} separate event groups. This is not full-market coverage."
    elif lens == 'special':
        brief = f'{len(special)} candidates meet the 24h price-move (5 pp) or balanced-odds (42–58%) screen.' if special else 'No qualifying price-move or balanced-odds candidates in the available sample.'
    else:
        brief = f'{len(themes)} sampled markets have a reported 24h probability change of at least 1 pp.' if themes else 'Comparable current and 24h-prior prices are unavailable, or no move reaches 1 pp. No trend is inferred.'
    return {
        'status': reason, 'generationMode': 'rules', 'lens': lens,
        'forecastRunId': compact_text(payload.get('forecastRunId') or payload.get('forecast_run_id'), 48),
        'generatedAt': _utc_now_iso(), 'model': 'deterministic-fallback', 'brief': brief,
        'focus': focus, 'specialMarkets': special if lens == 'special' else [], 'themes': themes,
        'watchlist': [], 'evidence': [f"{metrics['activeMarkets']} sampled markets", f"{metrics['marketGroups']} event groups", f"{metrics['tradeRows']} loaded trades", f"{metrics['contentItems']} content items"],
        'limitations': ['AI generation is unavailable; these are rules-based observations.', 'Sample coverage only. Event-group turnover is excluded from market totals.', 'No historical volume baseline or category-rotation claim. Reported prices require freshness checks.'],
        'metrics': metrics, 'searchResults': search_results or [], 'error': reason,
    }
