from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from agent.common.env import get_bool_env, get_int_env
from agent.common.json_utils import compact_text, extract_json_object


GRAPH_VERSION = "forecast-intelligence-graph-v1"
SPECIALIST_NODES = ("microstructure", "catalyst", "resolution")
FORECAST_ANALYST_RULES = """
Prediction-market usefulness rules:
- Do not write generic dashboard observations such as "activity is broad", "sports supplies count", or "liquidity is uneven" unless immediately tied to a named market and a price/volume/trade-count implication.
- Prefer market-level theses: named market, current implied probability, volume/trade-count, deadline or outcome bucket, catalyst, and resolution caveat.
- Surface probability structure: near-50c repricing zones, deadline ladders, term spreads, mutually related markets, one-sided liquidity, stale prices, and group-vs-single-market mismatches.
- Explain what would move the price next: official source, match result, court/government release, shipping/oil data, oracle update, or new large fills.
- Say "no directional edge" when price-change data is missing; then identify what data would be needed. Do not fill the gap with category commentary.
- Keep all claims informational. Do not recommend trades, position sizing, or financial advice.
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_hash(payload: Any) -> str:
    try:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    except Exception:
        raw = str(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def forecast_run_id(payload: dict[str, Any]) -> str:
    explicit = payload.get("forecastRunId") or payload.get("forecast_run_id")
    if explicit:
        return compact_text(explicit, 48)
    stable = {key: value for key, value in payload.items() if key not in {"lens", "forecastRunId", "forecast_run_id"}}
    return f"fig-{_json_hash(stable)}"


def graph_enabled() -> bool:
    return get_bool_env("POLYDATA_AGENT_MARKET_WIDE_GRAPH_ENABLED", True)


def _agent_limit() -> int:
    return max(0, min(4, get_int_env("POLYDATA_AGENT_MARKET_WIDE_GRAPH_AGENT_LIMIT", 4)))


def _compact_findings(items: Any, limit: int = 4) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    output: list[dict[str, str]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        output.append({
            "label": compact_text(item.get("label") or "SIGNAL", 16).upper(),
            "title": compact_text(item.get("title") or "Market signal", 90),
            "summary": compact_text(item.get("summary") or item.get("reason") or "", 180),
            "severity": compact_text(item.get("severity") or "neutral", 20).lower(),
            "evidence": compact_text(item.get("evidence") or "", 90),
        })
    return output


def _compact_string_list(items: Any, limit: int = 4) -> list[str]:
    if not isinstance(items, list):
        return []
    return [compact_text(item, 140) for item in items[:limit] if item]


def _normalize_node_output(raw: dict[str, Any], node: str) -> dict[str, Any]:
    return {
        "node": node,
        "findings": _compact_findings(raw.get("findings")),
        "risks": _compact_string_list(raw.get("risks")),
        "watch": _compact_string_list(raw.get("watch")),
        "confidence": compact_text(raw.get("confidence") or raw.get("confidenceLabel") or "medium", 24).lower(),
        "probabilityAdjustment": compact_text(raw.get("probabilityAdjustment") or raw.get("priceAdjustment") or "", 80),
    }


def _deterministic_evidence(context: dict[str, Any], lens: str) -> dict[str, Any]:
    metrics = context.get("metrics") if isinstance(context.get("metrics"), dict) else {}
    candidates = context.get("marketCandidates") if isinstance(context.get("marketCandidates"), list) else []
    top = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    top_categories = metrics.get("topCategories") if isinstance(metrics.get("topCategories"), list) else []
    return {
        "node": "evidence_builder",
        "lens": lens,
        "metrics": metrics,
        "topMarket": {
            "title": compact_text(top.get("title") or "No standout market", 100),
            "category": compact_text(top.get("category") or "market", 40),
            "volume24h": top.get("volume24h"),
            "tradeCount24h": top.get("tradeCount24h"),
            "latestPrice": top.get("latestPrice"),
        },
        "categoryConcentration": ", ".join(str(item) for item in top_categories[:4]) or "categories loading",
        "inputHash": _json_hash({
            "metrics": metrics,
            "candidates": candidates[:12],
            "search": context.get("searchResults", [])[:2],
        }),
    }


def _specialist_prompt(node: str, lens: str, context: dict[str, Any], evidence: dict[str, Any]) -> tuple[str, str]:
    role = {
        "microstructure": "You are the market microstructure agent for a Polymarket intelligence graph. Focus on named markets, implied probability, volume, trade-count, liquidity concentration, close probabilities, deadline ladders, and group-vs-single-market mismatches.",
        "catalyst": "You are the catalyst research agent for a Polymarket intelligence graph. Focus on named markets, current prices, concrete external triggers, related-market catalysts, event timing, and what news/data would move probability.",
        "resolution": "You are the resolution-risk agent for a Polymarket intelligence graph. Focus on market wording, deadline buckets, official source hierarchy, oracle/resolution events, ambiguity, and settlement risk that changes how prices should be interpreted.",
        "skeptic": "You are the skeptic and calibration agent for a Polymarket intelligence graph. Challenge weak evidence, missing price-change data, stale signals, narrative overreach, and probability miscalibration.",
    }[node]
    user_context = {
        "lens": lens,
        "evidence": evidence,
        "context": {
            "metrics": context.get("metrics"),
            "marketCandidates": context.get("marketCandidates", [])[:12],
            "markets": context.get("markets", [])[:8],
            "marketGroups": context.get("marketGroups", [])[:8],
            "trades": context.get("trades", [])[:6],
            "oracle": context.get("oracle", [])[:6],
            "content": context.get("content", [])[:6],
            "alphaSignals": context.get("alphaSignals", [])[:4],
            "whaleSignals": context.get("whaleSignals", [])[:4],
            "suspiciousSignals": context.get("suspiciousSignals", [])[:4],
            "searchResults": context.get("searchResults", [])[:3],
            "specialistAgents": context.get("specialistAgents", []),
        },
        "requiredSchema": {
            "findings": [{"label": "LIQUIDITY|CATALYST|RESOLUTION|RISK|TREND|PROBABILITY", "title": "named market or spread", "summary": "market-level insight with price/probability and why it matters", "severity": "positive|warning|critical|neutral", "evidence": "price + volume/trades"}],
            "risks": ["up to three risks or caveats"],
            "watch": ["up to three concrete triggers that would move probability"],
            "confidence": "low|medium|high",
            "probabilityAdjustment": "terse note on implied probability, term spread, or no directional edge",
        },
    }
    return role + FORECAST_ANALYST_RULES + "\nReturn compact JSON only.", json.dumps(user_context, ensure_ascii=False, default=str)


def _writer_prompt(lens: str, context: dict[str, Any], evidence: dict[str, Any], agents: list[dict[str, Any]], calibration: dict[str, Any]) -> tuple[str, str]:
    system = """You are the panel writer for polyData's Forecast Intelligence Graph.
Return compact JSON only. Use the specialist agent outputs as evidence, but write one coherent dashboard payload.
The user does not need a category summary. The user needs prediction-market intelligence: named markets, implied probabilities, why the market is priced that way, what could move it, and what resolution wording can break the read.
Write like a prediction-market analyst, not a dashboard narrator.
""" + FORECAST_ANALYST_RULES
    user = {
        "lens": lens,
        "architecture": GRAPH_VERSION,
        "evidenceBuilder": evidence,
        "specialistAgents": agents,
        "skepticCalibration": calibration,
        "sourceContext": {
            "metrics": context.get("metrics"),
            "marketCandidates": context.get("marketCandidates", [])[:18],
            "markets": context.get("markets", [])[:12],
            "marketGroups": context.get("marketGroups", [])[:12],
            "trades": context.get("trades", [])[:8],
            "oracle": context.get("oracle", [])[:8],
            "content": context.get("content", [])[:8],
            "searchResults": context.get("searchResults", [])[:3],
        },
        "requiredSchema": {
            "brief": "one or two concise English sentences. Must name at least one market and include a price/probability or spread. Avoid generic category/breadth wording.",
            "specialMarkets": [{"title": "exact market/event title", "why": "why this market matters in prediction-market terms: price, volume/trades, catalyst, resolution or term-structure", "trend": "probability structure label such as 50c repricing zone|deadline ladder|term spread|liquidity anomaly|resolution premium", "severity": "positive|warning|critical|neutral", "evidence": "price + volume/trades"}],
            "themes": [{"label": "PROBABILITY|CATALYST|RESOLUTION|LIQUIDITY|SPREAD|RISK|TREND", "title": "named market cluster or relationship", "summary": "specific thesis about pricing, curve, catalyst, or resolution; not category summary", "severity": "positive|warning|critical|neutral", "evidence": "short price/volume/trade evidence"}],
            "watchlist": [{"title": "specific market trigger", "reason": "what update would change implied probability or resolve ambiguity", "horizon": "today|24h|this week|event close", "severity": "positive|warning|critical|neutral"}],
            "focus": [{"label": "PROBABILITY|SPREAD|CATALYSTS|RESOLUTION|LIQUIDITY|RISK", "title": "market-level title", "summary": "one useful sentence with market, price/probability, and interpretation", "severity": "positive|warning|critical|neutral", "evidence": "price + flow evidence"}],
            "evidence": ["up to four terse bullets, each with a named market and numeric evidence"],
        },
    }
    return system, json.dumps(user, ensure_ascii=False, default=str)


def _call_json_node(client: Any, node: str, messages: list[dict[str, str]], *, max_tokens: int, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    started = _utc_now_iso()
    event: dict[str, Any] = {
        "node": node,
        "startedAt": started,
        "inputHash": _json_hash(messages),
        "status": "ok",
    }
    try:
        raw_text = client.complete_json(
            messages,
            max_tokens=max_tokens,
            workflow_name=f"polydata-market-wide-fig-{node}-{run_id}",
        )
        raw = extract_json_object(raw_text)
        output_hash = _json_hash(raw)
        usage = getattr(client, "last_usage", None)
        event.update({
            "finishedAt": _utc_now_iso(),
            "outputHash": output_hash,
            "model": getattr(client, "model", ""),
            "runtime": getattr(usage, "runtime", ""),
            "usage": {
                "inputTokens": getattr(usage, "input_tokens", 0),
                "outputTokens": getattr(usage, "output_tokens", 0),
                "totalTokens": getattr(usage, "total_tokens", 0),
                "inputChars": getattr(usage, "input_chars", 0),
            },
        })
        return raw, event
    except Exception as exc:
        event.update({
            "finishedAt": _utc_now_iso(),
            "status": "error",
            "error": compact_text(str(exc), 180),
        })
        return {}, event


def _usage_total(events: list[dict[str, Any]]) -> dict[str, int]:
    total = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "requests": 0}
    for event in events:
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        if usage:
            total["requests"] += 1
        total["inputTokens"] += int(usage.get("inputTokens") or 0)
        total["outputTokens"] += int(usage.get("outputTokens") or 0)
        total["totalTokens"] += int(usage.get("totalTokens") or 0)
    return total


def run_forecast_intelligence_graph(
    payload: dict[str, Any],
    lens: str,
    context: dict[str, Any],
    search_results: list[dict[str, str]],
    client: Any,
    *,
    normalize: Callable[[dict[str, Any], dict[str, Any], str, list[dict[str, str]], str], dict[str, Any]],
    fallback: Callable[[dict[str, Any], str, str, list[dict[str, str]]], dict[str, Any]],
) -> dict[str, Any]:
    run_id = forecast_run_id(payload)
    evidence = _deterministic_evidence(context, lens)
    events: list[dict[str, Any]] = [{
        "node": "evidence_builder",
        "status": "ok",
        "finishedAt": _utc_now_iso(),
        "inputHash": evidence["inputHash"],
        "outputHash": _json_hash(evidence),
    }]
    if not getattr(client, "configured", False):
        response = fallback(payload, lens, "missing-api-key", search_results)
        response["forecastRunId"] = run_id
        response["agentArchitecture"] = GRAPH_VERSION
        response["agentGraph"] = {"version": GRAPH_VERSION, "runId": run_id, "events": events, "mode": "deterministic-fallback"}
        return response

    limit = _agent_limit()
    specialists: list[dict[str, Any]] = []
    for node in SPECIALIST_NODES[:limit]:
        system, user = _specialist_prompt(node, lens, context, evidence)
        raw, event = _call_json_node(
            client,
            node,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=520,
            run_id=run_id,
        )
        events.append(event)
        specialists.append(_normalize_node_output(raw, node) if raw else {"node": node, "findings": [], "risks": [event.get("error", "agent failed")], "watch": [], "confidence": "low"})

    calibration: dict[str, Any] = {"node": "skeptic", "findings": [], "risks": [], "watch": [], "confidence": "medium"}
    if limit >= 4:
        system, user = _specialist_prompt("skeptic", lens, {**context, "specialistAgents": specialists}, evidence)
        raw, event = _call_json_node(
            client,
            "skeptic",
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=520,
            run_id=run_id,
        )
        events.append(event)
        if raw:
            calibration = _normalize_node_output(raw, "skeptic")

    system, user = _writer_prompt(lens, context, evidence, specialists, calibration)
    raw, event = _call_json_node(
        client,
        "panel_writer",
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=950,
        run_id=run_id,
    )
    events.append(event)
    if not raw:
        response = fallback(payload, lens, "agent-error", search_results)
    else:
        try:
            response = normalize(raw, payload, lens, search_results, getattr(client, "model", ""))
        except Exception as exc:
            events.append({
                "node": "response_normalizer",
                "status": "error",
                "finishedAt": _utc_now_iso(),
                "error": compact_text(str(exc), 180),
            })
            response = fallback(payload, lens, "agent-error", search_results)
    response["forecastRunId"] = run_id
    response["agentArchitecture"] = GRAPH_VERSION
    response["agentGraph"] = {
        "version": GRAPH_VERSION,
        "runId": run_id,
        "mode": "supervisor-worker",
        "nodes": ["evidence_builder", *SPECIALIST_NODES[:limit], *(["skeptic"] if limit >= 4 else []), "panel_writer"],
        "events": events,
        "specialists": specialists,
        "calibration": calibration,
    }
    response["usage"] = {**response.get("usage", {}), **_usage_total(events), "contextChars": context.get("contextChars")}
    response["agentRuntime"] = "forecast-intelligence-graph"
    return response
