from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from agent.common.env import get_bool_env, get_int_env
from agent.common.json_utils import compact_text, extract_json_object


GRAPH_VERSION = "forecast-intelligence-graph-v2"
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


def _as_float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if numeric == numeric else 0.0


def _fmt_compact(value: Any) -> str:
    numeric = _as_float(value)
    if abs(numeric) >= 1_000_000:
        return f"{numeric / 1_000_000:.1f}M"
    if abs(numeric) >= 1_000:
        return f"{numeric / 1_000:.1f}K"
    if numeric == int(numeric):
        return str(int(numeric))
    return f"{numeric:.1f}"


def _fmt_price(value: Any) -> str:
    numeric = _as_float(value)
    if numeric <= 0:
        return "n/a"
    return f"{numeric * 100:.1f}%"


def _fmt_money(value: Any) -> str:
    return f"${_fmt_compact(value)}"


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


def _compact_quant_for_prompt(quant: dict[str, Any]) -> dict[str, Any]:
    return {
        "topFlowMarkets": (quant.get("topFlowMarkets") or [])[:5],
        "repricingZones": (quant.get("repricingZones") or [])[:5],
        "anomalies": (quant.get("anomalies") or [])[:3],
        "dataWarnings": (quant.get("dataWarnings") or [])[:2],
    }


def _compact_related_for_prompt(related: dict[str, Any]) -> dict[str, Any]:
    return {
        "ladders": (related.get("ladders") or [])[:5],
        "anomalies": (related.get("anomalies") or [])[:3],
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


def _market_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("marketCandidates", "markets"):
        values = context.get(key) if isinstance(context.get(key), list) else []
        for item in values:
            if not isinstance(item, dict):
                continue
            title = compact_text(item.get("title") or item.get("market") or "Untitled market", 120)
            if not title or title in seen:
                continue
            seen.add(title)
            rows.append({
                "title": title,
                "category": compact_text(item.get("category") or "market", 40),
                "price": _as_float(item.get("latestPrice") or item.get("yesPrice") or item.get("price")),
                "volume24h": _as_float(item.get("volume24h")),
                "tradeCount24h": _as_float(item.get("tradeCount24h")),
                "change24h": item.get("change24h"),
                "endDate": item.get("endDate"),
                "kind": item.get("kind"),
            })
    return rows


def _price_band(price: float) -> str:
    if price <= 0:
        return "missing-price"
    if 0.48 <= price <= 0.52:
        return "50c-repricing-zone"
    if 0.42 <= price <= 0.58:
        return "contested-probability"
    if price >= 0.9:
        return "near-certain"
    if price <= 0.1:
        return "long-shot"
    return "priced-view"


def _build_quant_forecaster(context: dict[str, Any]) -> dict[str, Any]:
    rows = _market_rows(context)
    ranked_flow = sorted(
        rows,
        key=lambda item: (item["volume24h"], item["tradeCount24h"]),
        reverse=True,
    )
    near_repricing = sorted(
        [item for item in rows if 0.42 <= item["price"] <= 0.58 and (item["volume24h"] > 0 or item["tradeCount24h"] > 0)],
        key=lambda item: (item["volume24h"] * 2 + item["tradeCount24h"] * 200),
        reverse=True,
    )
    anomalies: list[dict[str, Any]] = []
    for item in rows:
        if item["volume24h"] >= 100_000 and item["tradeCount24h"] <= 2:
            anomalies.append({
                "title": item["title"],
                "type": "volume-without-trade-count",
                "evidence": f"{_fmt_money(item['volume24h'])}; {_fmt_compact(item['tradeCount24h'])} trades",
                "interpretation": "Treat as grouped aggregation, stale volume, or ingestion mismatch until fills reconcile.",
            })
        if item["price"] >= 0.98 and item["volume24h"] > 0:
            anomalies.append({
                "title": item["title"],
                "type": "near-certain-live-price",
                "evidence": f"{_fmt_price(item['price'])}; {_fmt_money(item['volume24h'])}",
                "interpretation": "Could be live/resolved/stale rather than a normal ex-ante probability.",
            })
    missing_change = sum(1 for item in rows if item.get("change24h") in (None, "", "null"))
    return {
        "node": "quant_forecaster",
        "universeSize": len(rows),
        "topFlowMarkets": [
            {
                "title": item["title"],
                "price": _fmt_price(item["price"]),
                "band": _price_band(item["price"]),
                "volume24h": _fmt_money(item["volume24h"]),
                "tradeCount24h": int(item["tradeCount24h"]),
                "endDate": item.get("endDate"),
            }
            for item in ranked_flow[:6]
        ],
        "repricingZones": [
            {
                "title": item["title"],
                "price": _fmt_price(item["price"]),
                "volume24h": _fmt_money(item["volume24h"]),
                "tradeCount24h": int(item["tradeCount24h"]),
                "why": "Price sits near 50c/contested territory where fresh information can move probability quickly.",
            }
            for item in near_repricing[:6]
        ],
        "anomalies": anomalies[:6],
        "dataWarnings": [
            f"{missing_change} market rows have missing change24h; directional momentum should not be inferred from volume alone."
        ] if missing_change else [],
        "inputHash": _json_hash(rows[:24]),
    }


def _group_outcomes(group: dict[str, Any]) -> list[dict[str, Any]]:
    raw = group.get("outcomes") if isinstance(group.get("outcomes"), list) else group.get("topOutcomes")
    outcomes: list[dict[str, Any]] = []
    for outcome in raw if isinstance(raw, list) else []:
        if not isinstance(outcome, dict):
            continue
        price = _as_float(outcome.get("yesPrice") or outcome.get("price") or outcome.get("latestPrice"))
        if price <= 0:
            continue
        outcomes.append({
            "label": compact_text(outcome.get("label") or outcome.get("title") or "Outcome", 72),
            "yesPrice": price,
            "volume24h": _as_float(outcome.get("volume24h")),
            "tradeCount24h": _as_float(outcome.get("tradeCount24h")),
        })
    return outcomes


def _build_related_markets(context: dict[str, Any]) -> dict[str, Any]:
    groups = context.get("marketGroups") if isinstance(context.get("marketGroups"), list) else []
    ladders: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        title = compact_text(group.get("title") or "Market group", 120)
        outcomes = _group_outcomes(group)
        if len(outcomes) < 2:
            continue
        prices = [item["yesPrice"] for item in outcomes]
        low = min(outcomes, key=lambda item: item["yesPrice"])
        high = max(outcomes, key=lambda item: item["yesPrice"])
        spread = high["yesPrice"] - low["yesPrice"]
        near = [item for item in outcomes if 0.42 <= item["yesPrice"] <= 0.58]
        if spread >= 0.15 or len(near) >= 2:
            ladders.append({
                "title": title,
                "type": "deadline-or-outcome-spread",
                "spread": f"{spread * 100:.1f} pts",
                "lowOutcome": {"label": low["label"], "price": _fmt_price(low["yesPrice"])},
                "highOutcome": {"label": high["label"], "price": _fmt_price(high["yesPrice"])},
                "near50Outcomes": [
                    {"label": item["label"], "price": _fmt_price(item["yesPrice"])}
                    for item in near[:4]
                ],
                "interpretation": "Related outcomes disagree enough to form a probability curve or repricing spread.",
            })
        if len(outcomes) >= 3 and all(item["yesPrice"] >= 0.98 for item in outcomes[:3]):
            anomalies.append({
                "title": title,
                "type": "multiple-near-certain-outcomes",
                "evidence": ", ".join(f"{item['label']} {_fmt_price(item['yesPrice'])}" for item in outcomes[:3]),
                "interpretation": "Likely live/resolved/stale ladder or feed issue; do not read as normal ex-ante probabilities.",
            })
        volume = _as_float(group.get("volume24h"))
        trades = _as_float(group.get("tradeCount24h"))
        if volume >= 100_000 and trades <= 2:
            anomalies.append({
                "title": title,
                "type": "group-volume-without-group-trades",
                "evidence": f"{_fmt_money(volume)} group volume; {_fmt_compact(trades)} group trades",
                "interpretation": "Check underlying child market fills before treating group volume as current flow.",
            })
    return {
        "node": "related_markets",
        "ladders": sorted(ladders, key=lambda item: _as_float(str(item.get("spread", "0")).split()[0]), reverse=True)[:8],
        "anomalies": anomalies[:8],
        "inputHash": _json_hash(groups[:20]),
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
            "marketCandidates": context.get("marketCandidates", [])[:8],
            "markets": context.get("markets", [])[:5],
            "marketGroups": context.get("marketGroups", [])[:4],
            "trades": context.get("trades", [])[:4],
            "oracle": context.get("oracle", [])[:4],
            "content": context.get("content", [])[:4],
            "alphaSignals": context.get("alphaSignals", [])[:2],
            "whaleSignals": context.get("whaleSignals", [])[:2],
            "suspiciousSignals": context.get("suspiciousSignals", [])[:2],
            "searchResults": context.get("searchResults", [])[:2],
            "specialistAgents": context.get("specialistAgents", []),
            "quantForecaster": _compact_quant_for_prompt(context.get("quantForecaster") or {}),
            "relatedMarkets": _compact_related_for_prompt(context.get("relatedMarkets") or {}),
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
            "quantForecaster": _compact_quant_for_prompt(context.get("quantForecaster") or {}),
            "relatedMarkets": _compact_related_for_prompt(context.get("relatedMarkets") or {}),
            "marketCandidates": context.get("marketCandidates", [])[:10],
            "markets": context.get("markets", [])[:6],
            "marketGroups": context.get("marketGroups", [])[:5],
            "trades": context.get("trades", [])[:4],
            "oracle": context.get("oracle", [])[:4],
            "content": context.get("content", [])[:4],
            "searchResults": context.get("searchResults", [])[:2],
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
    quant_forecaster = _build_quant_forecaster(context)
    related_markets = _build_related_markets(context)
    graph_context = {
        **context,
        "quantForecaster": quant_forecaster,
        "relatedMarkets": related_markets,
    }
    events: list[dict[str, Any]] = [{
        "node": "evidence_builder",
        "status": "ok",
        "finishedAt": _utc_now_iso(),
        "inputHash": evidence["inputHash"],
        "outputHash": _json_hash(evidence),
    }, {
        "node": "quant_forecaster",
        "status": "ok",
        "finishedAt": _utc_now_iso(),
        "inputHash": quant_forecaster["inputHash"],
        "outputHash": _json_hash(quant_forecaster),
    }, {
        "node": "related_markets",
        "status": "ok",
        "finishedAt": _utc_now_iso(),
        "inputHash": related_markets["inputHash"],
        "outputHash": _json_hash(related_markets),
    }]
    if not getattr(client, "configured", False):
        response = fallback(payload, lens, "missing-api-key", search_results)
        response["forecastRunId"] = run_id
        response["agentArchitecture"] = GRAPH_VERSION
        response["agentGraph"] = {
            "version": GRAPH_VERSION,
            "runId": run_id,
            "mode": "deterministic-fallback",
            "nodes": ["evidence_builder", "quant_forecaster", "related_markets"],
            "events": events,
            "quantForecaster": quant_forecaster,
            "relatedMarkets": related_markets,
        }
        return response

    limit = _agent_limit()
    specialists: list[dict[str, Any]] = []
    for node in SPECIALIST_NODES[:limit]:
        system, user = _specialist_prompt(node, lens, graph_context, evidence)
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
        system, user = _specialist_prompt("skeptic", lens, {**graph_context, "specialistAgents": specialists}, evidence)
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

    system, user = _writer_prompt(lens, graph_context, evidence, specialists, calibration)
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
        "nodes": ["evidence_builder", "quant_forecaster", "related_markets", *SPECIALIST_NODES[:limit], *(["skeptic"] if limit >= 4 else []), "panel_writer"],
        "events": events,
        "quantForecaster": quant_forecaster,
        "relatedMarkets": related_markets,
        "specialists": specialists,
        "calibration": calibration,
    }
    response["usage"] = {**response.get("usage", {}), **_usage_total(events), "contextChars": context.get("contextChars")}
    response["agentRuntime"] = "forecast-intelligence-graph"
    return response
