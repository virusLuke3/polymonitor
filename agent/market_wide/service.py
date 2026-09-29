from __future__ import annotations

import json
from typing import Any

from agent.common.env import get_int_env
from agent.common.json_utils import compact_text, extract_json_object
from agent.common.llm_client import OpenAICompatibleClient
from agent.common.tavily_client import TavilySearchClient

from .graph import graph_enabled, run_forecast_intelligence_graph
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .rules import (
    _fallback_response,
    _items,
    _market_candidates,
    _signal_items,
    _summary_metrics,
    _top_categories,
    _utc_now_iso,
)


VALID_LENSES = {"overview", "special", "trend"}
LENS_ALIASES = {
    "brief": "overview",
    "flow": "special",
    "oracle": "trend",
    "catalyst": "trend",
    "radar": "trend",
}


class _DeterministicFallbackClient:
    configured = False
    model = "deterministic-fallback"


def _compact_market(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "id": item.get("id") or item.get("localMarketId"),
        "conditionId": item.get("conditionId"),
        "yesTokenId": item.get("yesTokenId"),
        "noTokenId": item.get("noTokenId"),
        "title": compact_text(item.get("title") or item.get("slug") or "Untitled market", 120),
        "category": compact_text(item.get("category") or "market", 40),
        "volume24h": item.get("volume24h"),
        "tradeCount24h": item.get("tradeCount24h"),
        "latestPrice": item.get("latestPrice"),
        "price24hAgo": item.get("price24hAgo"),
        "change24h": item.get("change24h"),
        "bestBid": item.get("bestBid") or item.get("bid") or item.get("yesBid"),
        "bestAsk": item.get("bestAsk") or item.get("ask") or item.get("yesAsk"),
        "endDate": item.get("endDate"),
    }


def _compact_group(group: Any) -> dict[str, Any] | None:
    if not isinstance(group, dict):
        return None
    outcomes = group.get("topOutcomes") if isinstance(group.get("topOutcomes"), list) else group.get("outcomes")
    outcomes = outcomes if isinstance(outcomes, list) else []
    return {
        "title": compact_text(group.get("title") or group.get("slug") or "Untitled event", 120),
        "category": compact_text(group.get("category") or "market", 40),
        "volume24h": group.get("volume24h"),
        "tradeCount24h": group.get("tradeCount24h"),
        "outcomeCount": group.get("outcomeCount") or len(outcomes),
        "endDate": group.get("endDate"),
        "outcomes": [
            {
                "label": compact_text(outcome.get("label") or outcome.get("title"), 56),
                "yesPrice": outcome.get("yesPrice"),
                "volume24h": outcome.get("volume24h"),
                "tradeCount24h": outcome.get("tradeCount24h"),
            }
            for outcome in outcomes[:3]
            if isinstance(outcome, dict)
        ],
    }


def _compact_trade(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "marketId": item.get("marketId") or item.get("localMarketId"),
        "conditionId": item.get("conditionId"),
        "market": compact_text(item.get("marketTitle") or item.get("title") or item.get("conditionId"), 90),
        "outcome": compact_text(item.get("outcome") or item.get("assetName"), 48),
        "side": compact_text(item.get("side") or item.get("type"), 20),
        "price": item.get("price"),
        "size": item.get("size") or item.get("amount"),
        "timestamp": item.get("timestamp") or item.get("createdAt"),
    }


def _compact_fill_tape(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    fills = item.get("recentFills") if isinstance(item.get("recentFills"), list) else []
    return {
        "marketId": item.get("marketId"),
        "conditionId": item.get("conditionId"),
        "title": compact_text(item.get("title") or "Untitled market", 120),
        "category": compact_text(item.get("category") or "market", 40),
        "snapshotLatestPrice": item.get("snapshotLatestPrice"),
        "snapshotPrice24hAgo": item.get("snapshotPrice24hAgo"),
        "snapshotChange24h": item.get("snapshotChange24h"),
        "snapshotVolume24h": item.get("snapshotVolume24h"),
        "snapshotTradeCount24h": item.get("snapshotTradeCount24h"),
        "detailLatestPrice": item.get("detailLatestPrice"),
        "detailYesPrice": item.get("detailYesPrice"),
        "detailNoPrice": item.get("detailNoPrice"),
        "detailNoAsYesPrice": item.get("detailNoAsYesPrice"),
        "fillCountLoaded": item.get("fillCountLoaded"),
        "latestFillYesPrice": item.get("latestFillYesPrice"),
        "oldestLoadedFillYesPrice": item.get("oldestLoadedFillYesPrice"),
        "recentFillDrift": item.get("recentFillDrift"),
        "fillYesPriceRange": item.get("fillYesPriceRange"),
        "fillVwapYesPrice": item.get("fillVwapYesPrice"),
        "lastFillAt": item.get("lastFillAt"),
        "fillFreshness": item.get("fillFreshness"),
        "fillFreshnessSeconds": item.get("fillFreshnessSeconds"),
        "pairedFillRatio": item.get("pairedFillRatio"),
        "priceSourceConflict": bool(item.get("priceSourceConflict")),
        "recentFills": [
            {
                "timestamp": fill.get("timestamp"),
                "outcome": compact_text(fill.get("outcome"), 12),
                "side": compact_text(fill.get("side"), 12),
                "yesPrice": fill.get("yesPrice"),
                "size": fill.get("size"),
                "txHash": compact_text(fill.get("txHash"), 24),
            }
            for fill in fills[:8]
            if isinstance(fill, dict)
        ],
    }


def _compact_content(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "title": compact_text(item.get("title") or item.get("headline"), 120),
        "source": compact_text(item.get("source") or item.get("publisher"), 40),
        "summary": compact_text(item.get("summary") or item.get("content") or item.get("description"), 180),
        "publishedAt": item.get("publishedAt") or item.get("createdAt"),
    }


def _compact_signal(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "title": compact_text(item.get("title") or item.get("marketTitle") or item.get("label"), 110),
        "summary": compact_text(item.get("summary") or item.get("reason") or item.get("description"), 160),
        "severity": compact_text(item.get("severity") or item.get("level"), 20),
        "score": item.get("score") or item.get("value"),
        "timestamp": item.get("timestamp") or item.get("createdAt"),
    }


def _compact_oracle(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "title": compact_text(item.get("title") or item.get("marketTitle") or item.get("question"), 110),
        "status": compact_text(item.get("currentStatus") or item.get("status"), 40),
        "summary": compact_text(item.get("summary") or item.get("description") or item.get("resolution"), 160),
        "updatedAt": item.get("updatedAt") or item.get("timestamp"),
    }


def _compact_search_result(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    return {
        "title": compact_text(item.get("title"), 100),
        "content": compact_text(item.get("content"), 220),
        "url": compact_text(item.get("url"), 140),
    }


def _compact_forecast_memory(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    observation = item.get("observation") if isinstance(item.get("observation"), dict) else {}
    return {
        "memoryKey": item.get("memoryKey"),
        "runId": item.get("runId"),
        "kind": item.get("kind"),
        "title": compact_text(item.get("title"), 120),
        "lesson": compact_text(item.get("lesson"), 180),
        "createdAt": item.get("createdAt"),
        "brierScore": item.get("brierScore"),
        "observation": {
            "title": compact_text(observation.get("title"), 120),
            "score": observation.get("score"),
            "latestPrice": observation.get("latestPrice"),
            "price24hAgo": observation.get("price24hAgo"),
            "drift24h": observation.get("drift24h"),
            "spread": observation.get("spread"),
            "interpretation": compact_text(observation.get("interpretation"), 180),
        },
    }


def _compact_list(values: list[Any], limit: int, mapper: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for value in values[:limit]:
        compacted = mapper(value)
        if compacted:
            output.append(compacted)
    return output


def _limit_context_chars(context: dict[str, Any], max_chars: int) -> dict[str, Any]:
    if len(json.dumps(context, ensure_ascii=False, default=str)) <= max_chars:
        return context
    reduced = dict(context)
    for key, limit in (
        ("marketCandidates", 12),
        ("markets", 8),
        ("marketGroups", 6),
        ("topMarketFillTape", 5),
        ("content", 4),
        ("oracle", 4),
        ("alphaSignals", 4),
        ("whaleSignals", 4),
        ("suspiciousSignals", 4),
        ("trades", 4),
        ("searchResults", 2),
        ("forecastMemory", 8),
    ):
        if isinstance(reduced.get(key), list):
            reduced[key] = reduced[key][:limit]
    if len(json.dumps(reduced, ensure_ascii=False, default=str)) <= max_chars:
        return reduced
    for key in ("trades", "oracle", "alphaSignals", "whaleSignals", "suspiciousSignals", "searchResults"):
        reduced[key] = []
    if len(json.dumps(reduced, ensure_ascii=False, default=str)) <= max_chars:
        return reduced
    reduced["forecastMemory"] = reduced.get("forecastMemory", [])[:4] if isinstance(reduced.get("forecastMemory"), list) else []
    reduced["markets"] = reduced.get("markets", [])[:4] if isinstance(reduced.get("markets"), list) else []
    reduced["marketGroups"] = reduced.get("marketGroups", [])[:3] if isinstance(reduced.get("marketGroups"), list) else []
    reduced["topMarketFillTape"] = reduced.get("topMarketFillTape", [])[:3] if isinstance(reduced.get("topMarketFillTape"), list) else []
    reduced["marketCandidates"] = reduced.get("marketCandidates", [])[:8] if isinstance(reduced.get("marketCandidates"), list) else []
    return reduced


def _build_agent_context(payload: dict[str, Any], lens: str, search_results: list[dict[str, str]]) -> dict[str, Any]:
    max_chars = max(4_000, get_int_env("POLYDATA_AGENT_CONTEXT_MAX_CHARS", 24_000))
    context = {
        "lens": lens,
        "metrics": _summary_metrics(payload),
        "marketCandidates": _compact_list(_market_candidates(payload), 18, lambda item: {
            "id": item.get("id"),
            "conditionId": item.get("conditionId"),
            "title": compact_text(item.get("title"), 120),
            "category": compact_text(item.get("category"), 40),
            "kind": item.get("kind"),
            "volume24h": item.get("volume24h"),
            "tradeCount24h": item.get("tradeCount24h"),
            "latestPrice": item.get("latestPrice"),
            "price24hAgo": item.get("price24hAgo"),
            "change24h": item.get("change24h"),
            "bestBid": item.get("bestBid"),
            "bestAsk": item.get("bestAsk"),
            "outcomeCount": item.get("outcomeCount"),
            "endDate": item.get("endDate"),
        }),
        "markets": _compact_list(_items(payload, "markets"), 12, _compact_market),
        "marketGroups": _compact_list(_items(payload, "marketGroups"), 10, _compact_group),
        "topMarketFillTape": _compact_list(_items(payload, "topMarketFillTape"), 8, _compact_fill_tape),
        "trades": _compact_list(_items(payload, "trades"), 6, _compact_trade),
        "oracle": _compact_list(_items(payload, "oracle"), 6, _compact_oracle),
        "content": _compact_list(_items(payload, "content"), 6, _compact_content),
        "alphaSignals": _compact_list(_signal_items(payload, "alphaSignals"), 5, _compact_signal),
        "whaleSignals": _compact_list(_signal_items(payload, "whaleSignals"), 5, _compact_signal),
        "suspiciousSignals": _compact_list(_signal_items(payload, "suspiciousSignals"), 5, _compact_signal),
        "searchResults": _compact_list(search_results, 3, _compact_search_result),
        "forecastMemory": _compact_list(_items(payload, "forecastMemory"), 12, _compact_forecast_memory),
    }
    context = _limit_context_chars(context, max_chars)
    context["contextChars"] = len(json.dumps(context, ensure_ascii=False, default=str))
    context["contextMaxChars"] = max_chars
    return context


def _search_query(payload: dict[str, Any], lens: str) -> str:
    markets = _market_candidates(payload)
    titles = " ".join(str(item.get("title") or "") for item in markets[:6])
    categories = " ".join(_top_categories(markets))
    if lens == "special":
        prefix = "Polymarket unusual markets today volume probability trend"
    elif lens == "trend":
        prefix = "Polymarket market trends macro narratives prediction markets today"
    else:
        prefix = "Polymarket market brief today special markets catalysts trends"
    return compact_text(f"{prefix} {categories} {titles}", 320)


def _normalize(raw: dict[str, Any], payload: dict[str, Any], lens: str, search_results: list[dict[str, str]], model: str) -> dict[str, Any]:
    if not isinstance(raw.get("brief"), str) or not raw["brief"].strip() or any(
        not isinstance(raw.get(key), list) for key in ("focus", "specialMarkets", "themes", "watchlist", "evidence")
    ):
        return _fallback_response(payload, lens, reason="invalid-agent-output")
    fallback = _fallback_response(payload, lens, reason="fallback")
    focus_items = raw.get("focus") if isinstance(raw.get("focus"), list) else []
    focus: list[dict[str, str]] = []
    for item in focus_items[:5]:
        if not isinstance(item, dict):
            continue
        focus.append({
            "label": compact_text(item.get("label") or "SIGNAL", 16).upper(),
            "title": compact_text(item.get("title") or "Market-wide signal", 80),
            "summary": compact_text(item.get("summary") or "", 180),
            "severity": compact_text(item.get("severity") or "neutral", 20).lower(),
            "evidence": compact_text(item.get("evidence") or "", 80),
        })
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else fallback["evidence"]
    raw_special = raw.get("specialMarkets") if isinstance(raw.get("specialMarkets"), list) else []
    special_markets: list[dict[str, str]] = []
    for item in raw_special[:4]:
        if not isinstance(item, dict):
            continue
        special_markets.append({
            "title": compact_text(item.get("title") or "Special market", 90),
            "why": compact_text(item.get("why") or item.get("summary") or "", 160),
            "trend": compact_text(item.get("trend") or "Watch", 40),
            "severity": compact_text(item.get("severity") or "neutral", 20).lower(),
            "evidence": compact_text(item.get("evidence") or "", 80),
        })
    raw_themes = raw.get("themes") if isinstance(raw.get("themes"), list) else []
    themes: list[dict[str, str]] = []
    for item in raw_themes[:4]:
        if not isinstance(item, dict):
            continue
        themes.append({
            "label": compact_text(item.get("label") or "THEME", 16).upper(),
            "title": compact_text(item.get("title") or "Market theme", 80),
            "summary": compact_text(item.get("summary") or "", 180),
            "severity": compact_text(item.get("severity") or "neutral", 20).lower(),
            "evidence": compact_text(item.get("evidence") or "", 80),
        })
    raw_watchlist = raw.get("watchlist") if isinstance(raw.get("watchlist"), list) else []
    watchlist: list[dict[str, str]] = []
    for item in raw_watchlist[:4]:
        if not isinstance(item, dict):
            continue
        watchlist.append({
            "title": compact_text(item.get("title") or "Watch item", 90),
            "reason": compact_text(item.get("reason") or item.get("summary") or "", 160),
            "horizon": compact_text(item.get("horizon") or "today", 24),
            "severity": compact_text(item.get("severity") or "neutral", 20).lower(),
        })
    return {
        "status": "live",
        "generationMode": "ai",
        "lens": lens,
        "forecastRunId": compact_text(payload.get("forecastRunId") or payload.get("forecast_run_id"), 48),
        "generatedAt": _utc_now_iso(),
        "model": model,
        "brief": compact_text(raw.get("brief") or fallback["brief"], 260),
        "focus": focus,
        "specialMarkets": special_markets,
        "themes": themes,
        "watchlist": watchlist,
        "evidence": [compact_text(item, 120) for item in evidence[:4]],
        "metrics": _summary_metrics(payload),
        "searchResults": search_results,
    }


def build_market_wide_insight(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_response({}, "overview", reason="invalid-payload")
    lens = str(payload.get("lens") or "overview").strip().lower()
    lens = LENS_ALIASES.get(lens, lens)
    if lens not in VALID_LENSES:
        lens = "overview"
    search_results: list[dict[str, str]] = []
    try:
        search_results = TavilySearchClient().search(_search_query(payload, lens))
    except Exception:
        search_results = []
    context = _build_agent_context(payload, lens, search_results)
    client = OpenAICompatibleClient()
    if graph_enabled():
        return run_forecast_intelligence_graph(
            payload,
            lens,
            context,
            search_results,
            client,
            normalize=_normalize,
            fallback=lambda source_payload, source_lens, reason, results: _fallback_response(
                source_payload,
                source_lens,
                reason=reason,
                search_results=results,
            ),
        )
    if not client.configured:
        return _fallback_response(payload, lens, reason="missing-api-key", search_results=search_results)
    try:
        prompt = USER_PROMPT_TEMPLATE.replace("{lens}", lens).replace("{context_json}", json.dumps(context, ensure_ascii=False, default=str))
        raw_text = client.complete_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=950,
            workflow_name=f"polydata-market-wide-{lens}",
        )
        raw = extract_json_object(raw_text)
        response = _normalize(raw, payload, lens, search_results, client.model)
        response["agentRuntime"] = client.last_usage.runtime
        response["usage"] = {
            "inputTokens": client.last_usage.input_tokens,
            "outputTokens": client.last_usage.output_tokens,
            "totalTokens": client.last_usage.total_tokens,
            "inputChars": client.last_usage.input_chars,
            "contextChars": context.get("contextChars"),
        }
        return response
    except Exception as exc:
        response = _fallback_response(payload, lens, reason="agent-error", search_results=search_results)
        response["error"] = compact_text(str(exc), 180)
        return response


def build_market_wide_fallback(payload: dict[str, Any], *, reason: str = "cache-warming") -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _fallback_response({}, "overview", reason="invalid-payload")
    lens = str(payload.get("lens") or "overview").strip().lower()
    lens = LENS_ALIASES.get(lens, lens)
    if lens not in VALID_LENSES:
        lens = "overview"
    if graph_enabled():
        context = _build_agent_context(payload, lens, [])
        return run_forecast_intelligence_graph(
            payload,
            lens,
            context,
            [],
            _DeterministicFallbackClient(),
            normalize=_normalize,
            fallback=lambda source_payload, source_lens, _node_reason, results: _fallback_response(
                source_payload,
                source_lens,
                reason=reason,
                search_results=results,
            ),
        )
    return _fallback_response(payload, lens, reason=reason)
