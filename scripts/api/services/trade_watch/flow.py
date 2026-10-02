"""Oracle-window observations, explicitly separated from large-trade fallback."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict

from .. import outcome_semantics_service
from .common import SCHEMA_VERSION, _format_trade_item, parse_time, recent_large_trades


def fetch_live_suspicious_trades_payload(ctx: dict, limit: int = 12) -> Dict[str, Any]:
    generated_at = ctx["utc_now_iso"]()
    now = parse_time(generated_at)
    states: Dict[str, Any] = {}
    errors = []
    events = []
    try:
        source_events = ctx["get_recent_oracle_events"](limit=max(16, limit*2))
        if not isinstance(source_events, list):
            raise ValueError("Oracle source returned no assessment")
        seen = set()
        for event in source_events:
            stamp = parse_time(event.get("eventTime") or event.get("event_time"))
            market = str(event.get("marketId") or event.get("market_id") or "")
            # Ancient events cannot match the recent-fill candidate sample.
            if not market or not stamp or not now or not now-timedelta(hours=24) <= stamp <= now:
                continue
            key = (market, stamp)
            if key not in seen:
                seen.add(key)
                events.append((market, stamp, event))
        states["oracle"] = {"status": "ok", "recentEventCount": len(events)}
    except Exception:
        states["oracle"] = {"status": "error", "errorCode": "oracle-source-unavailable"}
        errors.append("Oracle events could not be checked; large trades are shown separately.")

    linked = []
    candidate_count = 0
    if events:
        try:
            trades = ctx["get_recent_trades"](limit=max(200, limit*30))
            if not isinstance(trades, list):
                raise ValueError("Trade source returned no assessment")
            candidate_count = len(trades)
            trades = outcome_semantics_service.annotate_raw_trade_rows(ctx, trades)
            seen = set()
            for trade in trades:
                market = str(trade.get("marketId") or trade.get("market_id") or "")
                stamp = parse_time(trade.get("timestamp"))
                if not stamp:
                    continue
                event = next((event for event_market, event_stamp, event in events
                              if market == event_market and event_stamp-timedelta(hours=6) <= stamp <= event_stamp), None)
                if event is None:
                    continue
                raw = dict(trade)
                if raw.get("notional") is None:
                    price, size = ctx["_safe_decimal"](raw.get("price")), ctx["_safe_decimal"](raw.get("size"))
                    if price is not None and size is not None:
                        raw["notional"] = price*size
                item = _format_trade_item(ctx, raw)
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                linked.append({**item, "observationType": "oracle-linked",
                               "eventStatus": event.get("eventStatus") or event.get("event_status"),
                               "eventTime": event.get("eventTime") or event.get("event_time"),
                               "summary": "Same-market fill within six hours before an Oracle event."})
            states["oracleTrades"] = {"status": "ok", "candidateCount": candidate_count}
        except Exception:
            states["oracleTrades"] = {"status": "error", "errorCode": "oracle-trades-unavailable"}
            errors.append("Oracle-window trades could not be checked.")
    else:
        states["oracleTrades"] = {"status": "not-needed", "candidateCount": 0}

    linked.sort(key=lambda item: ctx["_safe_decimal"](item.get("notional")) or Decimal("0"), reverse=True)
    items = linked[:limit]
    large_count = 0
    if len(items) < limit:
        try:
            large, state = recent_large_trades(ctx, limit)
            states["largeTrades"] = state
            seen = {item["id"] for item in items}
            for item in large:
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                items.append({**item, "observationType": "large-trade", "eventStatus": "heuristic",
                              "summary": "Large-trade observation; no Oracle relationship established."})
                large_count += 1
                if len(items) >= limit:
                    break
        except Exception:
            states["largeTrades"] = {"status": "error", "errorCode": "large-trades-unavailable"}
            errors.append("Large-trade source is unavailable.")
    else:
        states["largeTrades"] = {"status": "not-needed"}

    failures = any(state["status"] == "error" for state in states.values())
    return {"schemaVersion": SCHEMA_VERSION, "kind": "flow-watch", "items": items,
            "generatedAt": generated_at, "source": "Canonical OrderFilled and Oracle events",
            "sourceMode": "mixed" if linked and large_count else "oracle-linked" if linked else "large-trades",
            "status": "partial" if failures and items else "degraded" if failures else "ok" if items else "empty",
            "cacheMode": "live-build", "sourceStates": states, "error": " ".join(errors) or None,
            "coverage": {"oracleLinkedCount": min(len(linked), limit), "largeTradeCount": large_count,
                         "candidateTradeCount": candidate_count, "recentOracleEventCount": len(events),
                         "sampleLimit": max(200, limit*30), "limited": candidate_count >= max(200, limit*30),
                         "labelVerifiedCount": sum(item.get("outcomeSemanticsValid") is True for item in items)}}
