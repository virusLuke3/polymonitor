#!/usr/bin/env python3
"""Refresh current active-market serving metrics from Polymarket Gamma.

Market discovery is intentionally incremental and should not have to rescan all
historical markets just to keep the homepage catalog current.  This bounded
job polls the highest-volume and newest active events, matches them to the
canonical PostgreSQL market identities, and replaces rolling Gamma metrics
with their current values.

The job never invents markets and never writes rows that cannot be matched to
an existing canonical condition, Gamma market id, or slug.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_scripts_root = Path(__file__).resolve().parent.parent
if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))

from db import (  # type: ignore
    add_db_cli_args,
    configure_db_from_args,
    describe_db_target,
    get_connection,
    is_postgres_backend,
)


DEFAULT_GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_PAGES_PER_ORDER = 6
DEFAULT_TARGET_EVENTS = 600
DEFAULT_TIMEOUT_SECONDS = 15


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_list(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return [item.strip() for item in value.split(",") if item.strip()]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not numeric.is_finite():
        return None
    return numeric


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != ""), None)


def _probability(value: Any) -> Optional[Decimal]:
    numeric = _decimal(value)
    if numeric is None or numeric < 0 or numeric > 1:
        return None
    return numeric


def _normalize_condition(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text if text.startswith("0x") else f"0x{text}"


def _parse_timestamp(value: Any) -> float:
    if not value:
        return 0.0
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _market_is_open(market: Dict[str, Any]) -> bool:
    return not (
        market.get("closed") is True
        or market.get("active") is False
        or market.get("acceptingOrders") is False
    )


def _fetch_events(
    base_url: str,
    *,
    order: str,
    pages: int,
    target_events: int,
    timeout_seconds: int,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    seen: set[str] = set()
    limit = 100
    for page in range(max(1, int(pages))):
        query = urllib.parse.urlencode(
            {
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": page * limit,
                "order": order,
                "ascending": "false",
            }
        )
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/events?{query}",
            headers={"Accept": "application/json", "User-Agent": "polydata-active-market-refresh/1.0"},
        )
        with urllib.request.urlopen(request, timeout=max(3, int(timeout_seconds))) as response:
            payload = json.loads(response.read().decode("utf-8"))
        page_events = payload if isinstance(payload, list) else ((payload or {}).get("events") or (payload or {}).get("data") or [])
        if not isinstance(page_events, list) or not page_events:
            break
        for event in page_events:
            if not isinstance(event, dict):
                continue
            identity = str(event.get("id") or event.get("slug") or "").strip()
            if not identity or identity in seen:
                continue
            seen.add(identity)
            events.append(event)
            if len(events) >= target_events:
                return events
        if len(page_events) < limit:
            break
    return events


def _merge_events(*groups: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for events in groups:
        for event in events:
            identity = str(event.get("id") or event.get("slug") or "").strip()
            if not identity or identity in seen:
                continue
            seen.add(identity)
            merged.append(event)
    return merged


def _market_snapshot(event: Dict[str, Any], market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    is_open = _market_is_open(market)
    is_closed = market.get("closed") is True
    prices = _as_list(market.get("outcomePrices") or market.get("outcome_prices"))
    yes_price = _probability(prices[0]) if prices else None
    no_price = _probability(prices[1]) if len(prices) > 1 else None
    if yes_price is None:
        yes_price = _probability(market.get("lastTradePrice") or market.get("last_trade_price"))
    if no_price is None and yes_price is not None:
        no_price = Decimal("1") - yes_price
    change_24h = _decimal(market.get("oneDayPriceChange") or market.get("one_day_price_change"))
    price_24h_ago: Optional[Decimal] = None
    if yes_price is not None and change_24h is not None:
        candidate = yes_price - change_24h
        if 0 <= candidate <= 1:
            price_24h_ago = candidate
    source_updated_at = (
        market.get("updatedAt")
        or market.get("updated_at")
        or event.get("updatedAt")
        or event.get("updated_at")
    )
    if not source_updated_at:
        return None
    volume_24h = _decimal(
        _first_present(market.get("volume24hr"), market.get("volume_24hr"), market.get("volume24h"))
    )
    return {
        "condition_id": _normalize_condition(market.get("conditionId") or market.get("condition_id")),
        "gamma_market_id": str(market.get("id") or market.get("gamma_market_id") or "").strip(),
        "slug": str(market.get("slug") or "").strip(),
        "event_id": str(event.get("id") or "").strip(),
        "event_slug": str(event.get("slug") or event.get("ticker") or "").strip(),
        "event_title": str(event.get("title") or "").strip(),
        "end_date": market.get("endDate") or market.get("end_date") or event.get("endDate"),
        "yes_price": yes_price,
        "no_price": no_price,
        "price_24h_ago": price_24h_ago,
        "volume_24h": max(Decimal("0"), volume_24h or Decimal("0")) if not is_closed else Decimal("0"),
        "source_updated_at": str(source_updated_at),
        "is_open": is_open,
        "is_closed": is_closed,
    }


def _event_snapshots(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    snapshots: List[Dict[str, Any]] = []
    for event in events:
        for market in event.get("markets") or []:
            if not isinstance(market, dict):
                continue
            snapshot = _market_snapshot(event, market)
            if snapshot and (snapshot["condition_id"] or snapshot["gamma_market_id"] or snapshot["slug"]):
                snapshots.append(snapshot)
    return snapshots


def _chunks(values: Iterable[str], size: int = 450) -> Iterable[List[str]]:
    batch: List[str] = []
    for value in values:
        if not value:
            continue
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _lookup_market_ids(conn: Any, column: str, values: Iterable[str]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    normalized = sorted({str(value).strip() for value in values if str(value).strip()})
    for batch in _chunks(normalized):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"SELECT id, COALESCE({column}, '') AS identity FROM core.markets WHERE {column} IN ({placeholders})",
            batch,
        ).fetchall()
        for row in rows:
            data = row.as_dict() if hasattr(row, "as_dict") else dict(row)
            result.setdefault(str(data.get("identity") or ""), int(data["id"]))
    return result


def _matched_snapshots(conn: Any, snapshots: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    by_condition = _lookup_market_ids(conn, "condition_id", (item["condition_id"] for item in snapshots))
    by_gamma = _lookup_market_ids(conn, "gamma_market_id", (item["gamma_market_id"] for item in snapshots))
    by_slug = _lookup_market_ids(conn, "slug", (item["slug"] for item in snapshots))
    matched: Dict[int, Dict[str, Any]] = {}
    for snapshot in snapshots:
        market_id = (
            by_condition.get(str(snapshot["condition_id"]))
            or by_gamma.get(str(snapshot["gamma_market_id"]))
            or by_slug.get(str(snapshot["slug"]))
        )
        if market_id is None:
            continue
        current = matched.get(market_id)
        if current is None or (
            _parse_timestamp(snapshot["source_updated_at"]), snapshot["volume_24h"]
        ) > (
            _parse_timestamp(current["source_updated_at"]), current["volume_24h"]
        ):
            matched[market_id] = snapshot
    return matched


def _write_snapshots(conn: Any, matched: Dict[int, Dict[str, Any]]) -> Dict[str, int]:
    if not matched:
        return {"matched": 0, "marketMetadata": 0, "latestPrices": 0, "marketServing": 0, "marketStatus": 0}
    metadata_rows: List[Tuple[Any, ...]] = []
    price_rows: List[Tuple[Any, ...]] = []
    serving_rows: List[Tuple[Any, ...]] = []
    status_rows: List[Tuple[Any, ...]] = []
    for market_id, item in matched.items():
        metadata_rows.append(
            (
                item["event_id"],
                item["event_slug"],
                item["event_title"],
                item["gamma_market_id"],
                item["end_date"],
                market_id,
            )
        )
        if not item["is_closed"]:
            price_rows.append(
                (
                    market_id,
                    item["source_updated_at"],
                    item["yes_price"],
                    item["source_updated_at"],
                    item["yes_price"],
                    item["source_updated_at"],
                    item["no_price"],
                )
            )
        serving_rows.append(
            (
                market_id,
                item["yes_price"] if not item["is_closed"] else None,
                item["source_updated_at"] if not item["is_closed"] else None,
                item["price_24h_ago"] if not item["is_closed"] else None,
                item["volume_24h"],
                item["source_updated_at"] if item["volume_24h"] > 0 else None,
            )
        )
        status_rows.append(
            (
                market_id,
                item["is_closed"],
                item["source_updated_at"] if item["is_closed"] else None,
            )
        )

    conn.executemany(
        """
            UPDATE core.markets
            SET event_id = COALESCE(NULLIF(?, ''), event_id),
                event_slug = COALESCE(NULLIF(?, ''), event_slug),
                event_title = COALESCE(NULLIF(?, ''), event_title),
                gamma_market_id = COALESCE(NULLIF(?, ''), gamma_market_id),
                end_date = COALESCE(?, end_date)
            WHERE id = ?
        """,
        metadata_rows,
    )

    if price_rows:
        conn.executemany(
            """
        INSERT INTO core.market_latest_prices (
          market_id, latest_trade_at, latest_price,
          latest_yes_trade_at, latest_yes_price,
          latest_no_trade_at, latest_no_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (market_id) DO UPDATE SET
          latest_trade_at = CASE
            WHEN core.market_latest_prices.latest_trade_block IS NULL
             AND EXCLUDED.latest_trade_at >= COALESCE(core.market_latest_prices.latest_trade_at, '-infinity'::timestamptz)
            THEN EXCLUDED.latest_trade_at ELSE core.market_latest_prices.latest_trade_at END,
          latest_price = CASE
            WHEN core.market_latest_prices.latest_trade_block IS NULL
             AND EXCLUDED.latest_trade_at >= COALESCE(core.market_latest_prices.latest_trade_at, '-infinity'::timestamptz)
            THEN EXCLUDED.latest_price ELSE core.market_latest_prices.latest_price END,
          latest_yes_trade_at = CASE
            WHEN core.market_latest_prices.latest_yes_trade_block IS NULL
             AND EXCLUDED.latest_yes_trade_at >= COALESCE(core.market_latest_prices.latest_yes_trade_at, '-infinity'::timestamptz)
            THEN EXCLUDED.latest_yes_trade_at ELSE core.market_latest_prices.latest_yes_trade_at END,
          latest_yes_price = CASE
            WHEN core.market_latest_prices.latest_yes_trade_block IS NULL
             AND EXCLUDED.latest_yes_trade_at >= COALESCE(core.market_latest_prices.latest_yes_trade_at, '-infinity'::timestamptz)
            THEN EXCLUDED.latest_yes_price ELSE core.market_latest_prices.latest_yes_price END,
          latest_no_trade_at = CASE
            WHEN core.market_latest_prices.latest_no_trade_block IS NULL
             AND EXCLUDED.latest_no_trade_at >= COALESCE(core.market_latest_prices.latest_no_trade_at, '-infinity'::timestamptz)
            THEN EXCLUDED.latest_no_trade_at ELSE core.market_latest_prices.latest_no_trade_at END,
          latest_no_price = CASE
            WHEN core.market_latest_prices.latest_no_trade_block IS NULL
             AND EXCLUDED.latest_no_trade_at >= COALESCE(core.market_latest_prices.latest_no_trade_at, '-infinity'::timestamptz)
            THEN EXCLUDED.latest_no_price ELSE core.market_latest_prices.latest_no_price END,
          updated_at = now()
            """,
            price_rows,
        )
    conn.executemany(
        """
        INSERT INTO core.market_list_serving (
          market_id, latest_price, latest_trade_at, price_24h_ago,
          trade_count_24h, volume_24h, last_trade_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?)
        ON CONFLICT (market_id) DO UPDATE SET
          latest_price = COALESCE(EXCLUDED.latest_price, core.market_list_serving.latest_price),
          latest_trade_at = COALESCE(EXCLUDED.latest_trade_at, core.market_list_serving.latest_trade_at),
          price_24h_ago = COALESCE(EXCLUDED.price_24h_ago, core.market_list_serving.price_24h_ago),
          volume_24h = EXCLUDED.volume_24h,
          last_trade_at = COALESCE(EXCLUDED.last_trade_at, core.market_list_serving.last_trade_at),
          updated_at = now()
        """,
        serving_rows,
    )
    conn.executemany(
        """
        INSERT INTO core.market_status_snapshot (
          market_id, gamma_closed, gamma_closed_time, is_trading_closed
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT (market_id) DO UPDATE SET
          gamma_closed = EXCLUDED.gamma_closed,
          gamma_closed_time = EXCLUDED.gamma_closed_time,
          is_trading_closed = CASE
            WHEN EXCLUDED.gamma_closed THEN TRUE
            WHEN core.market_status_snapshot.is_final = FALSE
             AND core.market_status_snapshot.is_resolved = FALSE
             AND core.market_status_snapshot.completion_status = 'OPEN'
            THEN FALSE
            ELSE core.market_status_snapshot.is_trading_closed
          END,
          updated_at = now()
        """,
        [(market_id, gamma_closed, closed_at, gamma_closed) for market_id, gamma_closed, closed_at in status_rows],
    )
    conn.commit()
    return {
        "matched": len(matched),
        "marketMetadata": len(metadata_rows),
        "latestPrices": len(price_rows),
        "marketServing": len(serving_rows),
        "marketStatus": len(status_rows),
    }


def _event_metric_rows(events: Sequence[Dict[str, Any]]) -> List[Tuple[Any, ...]]:
    fetched_at = _utc_now_iso()
    rows: List[Tuple[Any, ...]] = []
    for event in events:
        event_id = str(event.get("id") or "").strip()
        volume_24h = _decimal(
            _first_present(event.get("volume24hr"), event.get("volume_24hr"), event.get("volume24h"))
        )
        if not event_id or volume_24h is None:
            continue
        source_updated_at = event.get("updatedAt") or event.get("updated_at") or fetched_at
        rows.append((max(Decimal("0"), volume_24h), str(source_updated_at), fetched_at, event_id))
    return rows


def _write_event_metrics(conn: Any, events: Sequence[Dict[str, Any]]) -> int:
    rows = _event_metric_rows(events)
    if not rows:
        return 0
    for sql in (
        "ALTER TABLE core.event_market_serving ADD COLUMN IF NOT EXISTS gamma_volume_24h NUMERIC(38, 18)",
        "ALTER TABLE core.event_market_serving ADD COLUMN IF NOT EXISTS gamma_volume_updated_at TIMESTAMPTZ",
        "ALTER TABLE core.event_market_serving ADD COLUMN IF NOT EXISTS gamma_volume_fetched_at TIMESTAMPTZ",
    ):
        conn.execute(sql)
    conn.executemany(
        """
        UPDATE core.event_market_serving
        SET gamma_volume_24h = ?,
            gamma_volume_updated_at = ?,
            gamma_volume_fetched_at = ?,
            volume_24h = ?,
            source = 'gamma-event',
            updated_at = now()
        WHERE event_id = ?
        """,
        [(volume, updated_at, fetched_at, volume, event_id) for volume, updated_at, fetched_at, event_id in rows],
    )
    conn.commit()
    return len(rows)


def refresh_active_market_serving(
    *,
    base_url: str,
    pages: int,
    target_events: int,
    timeout_seconds: int,
    dry_run: bool,
) -> Dict[str, Any]:
    fetched: Dict[str, List[Dict[str, Any]]] = {}
    errors: Dict[str, str] = {}
    for order in ("volume24hr", "startDate"):
        try:
            fetched[order] = _fetch_events(
                base_url,
                order=order,
                pages=pages,
                target_events=target_events,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            errors[order] = f"{exc.__class__.__name__}: {exc}"
            fetched[order] = []
    events = _merge_events(fetched["volume24hr"], fetched["startDate"])
    if not events:
        raise RuntimeError(f"Gamma active event refresh returned no events: {errors}")
    snapshots = _event_snapshots(events)
    conn = get_connection()
    try:
        matched = _matched_snapshots(conn, snapshots)
        if dry_run:
            write_stats = {
                "matched": len(matched),
                "marketMetadata": 0,
                "latestPrices": 0,
                "marketServing": 0,
                "marketStatus": 0,
                "eventMetrics": len(_event_metric_rows(events)),
            }
        else:
            write_stats = _write_snapshots(conn, matched)
            write_stats["eventMetrics"] = _write_event_metrics(conn, events)
    finally:
        conn.close()
    return {
        "status": "dry-run" if dry_run else "ok",
        "generatedAt": _utc_now_iso(),
        "events": len(events),
        "volumeEvents": len(fetched["volume24hr"]),
        "newEvents": len(fetched["startDate"]),
        "marketSnapshots": len(snapshots),
        "openMarketSnapshots": sum(1 for item in snapshots if item.get("is_open")),
        "closedMarketSnapshots": sum(1 for item in snapshots if item.get("is_closed")),
        "errors": errors,
        **write_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh current Gamma activity into PostgreSQL market serving tables.")
    add_db_cli_args(parser)
    parser.add_argument("--gamma-api-base", default=DEFAULT_GAMMA_API_BASE)
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES_PER_ORDER)
    parser.add_argument("--target-events", type=int, default=DEFAULT_TARGET_EVENTS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    configure_db_from_args(args)
    if not is_postgres_backend():
        raise SystemExit("active market serving refresh is PostgreSQL-only")
    print(f"[active-market-serving] target={describe_db_target()}", file=sys.stderr)
    stats = refresh_active_market_serving(
        base_url=args.gamma_api_base,
        pages=max(1, int(args.pages)),
        target_events=max(1, int(args.target_events)),
        timeout_seconds=max(3, int(args.timeout)),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
