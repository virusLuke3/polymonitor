from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from agent.common.env import get_bool_env, get_int_env
from agent.common.json_utils import compact_text, extract_json_object


GRAPH_VERSION = "forecast-intelligence-graph-v1"
SPECIALIST_NODES = ("microstructure", "catalyst", "resolution")


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
        "microstructure": "You are the market microstructure agent for a Polymarket intelligence graph. Focus on price, volume, trade-flow, liquidity, close probabilities, and unusual clusters.",
        "catalyst": "You are the catalyst research agent for a Polymarket intelligence graph. Focus on news, content, search results, category rotation, and event catalysts.",
        "resolution": "You are the resolution-risk agent for a Polymarket intelligence graph. Focus on market wording, oracle/resolution events, ambiguity, and settlement risk.",
        "skeptic": "You are the skeptic and calibration agent for a Polymarket intelligence graph. Challenge weak evidence, stale signals, narrative overreach, and probability miscalibration.",
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
            "findings": [{"label": "LIQUIDITY|CATALYST|RESOLUTION|RISK|TREND", "title": "short title", "summary": "short evidence-grounded sentence", "severity": "positive|warning|critical|neutral", "evidence": "short value"}],
            "risks": ["up to three risks or caveats"],
            "watch": ["up to three things to watch next"],
            "confidence": "low|medium|high",
            "probabilityAdjustment": "terse adjustment note, if relevant",
        },
    }
    return role + " Return compact JSON only. Do not provide financial advice.", json.dumps(user_context, ensure_ascii=False, default=str)


def _writer_prompt(lens: str, context: dict[str, Any], evidence: dict[str, Any], agents: list[dict[str, Any]], calibration: dict[str, Any]) -> tuple[str, str]:
    system = """You are the panel writer for polyData's Forecast Intelligence Graph.
Return compact JSON only. Use the specialist agent outputs as evidence, but write one coherent dashboard payload.
Do not provide financial advice. Phrase conclusions as prediction-market structure, catalyst, and resolution-risk signals."""
    user = {
        "lens": lens,
        "architecture": GRAPH_VERSION,
        "evidenceBuilder": evidence,
        "specialistAgents": agents,
        "skepticCalibration": calibration,
        "sourceContext": {
            "metrics": context.get("metrics"),
            "marketCandidates": context.get("marketCandidates", [])[:12],
            "searchResults": context.get("searchResults", [])[:3],
        },
        "requiredSchema": {
            "brief": "one or two concise English sentences; concrete conclusion first",
            "specialMarkets": [{"title": "market/event title", "why": "why unusual", "trend": "short label", "severity": "positive|warning|critical|neutral", "evidence": "short value"}],
            "themes": [{"label": "MACRO|SPORTS|CRYPTO|POLITICS|RISK|LIQUIDITY|TREND", "title": "theme", "summary": "broader Polymarket implication", "severity": "positive|warning|critical|neutral", "evidence": "short value"}],
            "watchlist": [{"title": "thing to watch", "reason": "why it matters", "horizon": "today|24h|this week|event close", "severity": "positive|warning|critical|neutral"}],
            "focus": [{"label": "BREADTH|SPECIAL|TREND|RISK|CATALYSTS|LIQUIDITY|ATTENTION", "title": "short title", "summary": "one concise sentence", "severity": "positive|warning|critical|neutral", "evidence": "short value"}],
            "evidence": ["up to four terse evidence bullets"],
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
