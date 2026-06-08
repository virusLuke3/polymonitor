from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.api.read_api import (  # noqa: E402
    get_backtest_equity,
    get_backtest_metrics,
    get_backtest_run,
    get_backtest_trades,
    get_block_close_prices,
    get_event_price_tile,
    get_event_price_series,
    get_frontend_prices,
    get_market_price_series,
    get_price_build_status,
    get_quant_price_events,
    get_quant_price_markets,
)
from quant.backtest.backtest_engine import create_backtest_run  # noqa: E402
from quant.core.db import PostgresSettings, postgres_connection  # noqa: E402
from quant.core.schema import create_schema  # noqa: E402


def _parse_int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _parse_time_arg(name: str) -> int | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def _camel_row(row: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "token_id": "tokenId",
        "market_id": "marketId",
        "market_slug": "marketSlug",
        "token_side": "tokenSide",
        "ts_minute": "tsMinute",
        "block_number": "blockNumber",
        "close_price": "closePrice",
        "yes_probability_close": "yesProbabilityClose",
        "vwap_price": "vwapPrice",
        "yes_probability_vwap": "yesProbabilityVwap",
        "close_raw_price": "closeRawPrice",
        "close_price_source": "closePriceSource",
        "close_tx_hash": "closeTxHash",
        "close_log_index": "closeLogIndex",
        "trade_count": "tradeCount",
        "raw_trade_count": "rawTradeCount",
        "run_id": "runId",
        "started_at": "startedAt",
        "finished_at": "finishedAt",
        "requested_from_ts": "requestedFromTs",
        "requested_to_ts": "requestedToTs",
        "requested_from_block": "requestedFromBlock",
        "requested_to_block": "requestedToBlock",
        "markets_total": "marketsTotal",
        "markets_complete": "marketsComplete",
        "rows_written": "rowsWritten",
        "error_count": "errorCount",
        "last_error": "lastError",
        "price_source": "priceSource",
        "backtest_engine": "backtestEngine",
        "from_ts": "fromTs",
        "to_ts": "toTs",
        "from_block": "fromBlock",
        "to_block": "toBlock",
        "rows_processed": "rowsProcessed",
        "created_at": "createdAt",
        "entry_threshold": "entryThreshold",
        "exit_threshold": "exitThreshold",
        "stop_loss": "stopLoss",
        "take_profit": "takeProfit",
        "max_holding_bars": "maxHoldingBars",
        "initial_capital": "initialCapital",
        "position_size": "positionSize",
        "metric_key": "metricKey",
        "metric_name": "metricName",
        "metric_group": "metricGroup",
        "formatted_value": "formattedValue",
        "sort_order": "sortOrder",
        "point_index": "pointIndex",
        "x_axis": "xAxis",
        "x_value": "xValue",
        "drawdown_pct": "drawdownPct",
        "cumulative_return": "cumulativeReturn",
        "trade_id": "tradeId",
        "entry_x": "entryX",
        "exit_x": "exitX",
        "entry_price": "entryPrice",
        "exit_price": "exitPrice",
        "pnl_pct": "pnlPct",
        "holding_bars": "holdingBars",
        "exit_reason": "exitReason",
        "block_rows": "blockRows",
        "frontend_rows": "frontendRows",
        "first_block": "firstBlock",
        "last_block": "lastBlock",
        "latest_block_price": "latestBlockPrice",
        "latest_block_at": "latestBlockAt",
        "first_ts": "firstTs",
        "last_ts": "lastTs",
        "latest_frontend_price": "latestFrontendPrice",
        "latest_frontend_at": "latestFrontendAt",
        "market_title": "marketTitle",
        "item_kind": "itemKind",
        "event_id": "eventId",
        "event_slug": "eventSlug",
        "event_title": "eventTitle",
        "event_category": "eventCategory",
        "event_subcategory": "eventSubcategory",
        "event_image_url": "eventImageUrl",
        "event_icon_url": "eventIconUrl",
        "event": "event",
        "members": "members",
        "outcome_count": "outcomeCount",
        "total_members": "totalMembers",
        "ready_members": "readyMembers",
        "orderfilled_rows": "orderfilledRows",
        "grouping_confidence": "groupingConfidence",
        "coverage_status": "coverageStatus",
        "outcome_key": "outcomeKey",
        "condition_id": "conditionId",
        "end_date": "endDate",
        "outcome_index": "outcomeIndex",
        "outcome_label": "outcomeLabel",
        "buy_yes_token_id": "buyYesTokenId",
        "buy_yes_token_side": "buyYesTokenSide",
        "buy_yes_label": "buyYesLabel",
        "buy_yes_price": "buyYesPrice",
        "buy_no_token_id": "buyNoTokenId",
        "buy_no_token_side": "buyNoTokenSide",
        "buy_no_label": "buyNoLabel",
        "buy_no_price": "buyNoPrice",
        "first_x": "firstX",
        "last_x": "lastX",
        "latest_price": "latestPrice",
        "complement_rows": "complementRows",
        "complement_first_x": "complementFirstX",
        "complement_last_x": "complementLastX",
        "complement_latest_price": "complementLatestPrice",
        "complement_points": "complementPoints",
        "x_axis": "xAxis",
        "yes_probability_close": "yesProbabilityClose",
        "yes_probability_vwap": "yesProbabilityVwap",
        "top_n": "topN",
        "max_points": "maxPoints",
        "source_limit": "sourceLimit",
    }
    return {mapping.get(key, key): _camel_value(value, mapping) for key, value in row.items()}


def _camel_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {mapping.get(key, key): _camel_value(inner, mapping) for key, inner in value.items()}
    if isinstance(value, list):
        return [_camel_value(item, mapping) for item in value]
    return _json_value(value)


def _lite_point(point: dict[str, Any]) -> dict[str, Any]:
    keys = ("x", "timestamp", "block_number", "price", "volume", "is_implied")
    return {key: point[key] for key in keys if point.get(key) is not None}


def _apply_point_payload_format(payload: dict[str, Any], point_format: str) -> dict[str, Any]:
    if point_format != "lite":
        return payload
    for outcome in payload.get("outcomes") or []:
        if isinstance(outcome, dict):
            outcome["points"] = [_lite_point(point) for point in outcome.get("points") or [] if isinstance(point, dict)]
            outcome["complement_points"] = [
                _lite_point(point) for point in outcome.get("complement_points") or [] if isinstance(point, dict)
            ]
    return payload


def create_quant_blueprint(helpers: dict) -> Blueprint:
    bp = Blueprint("quant_routes", __name__, url_prefix="/quant")
    get_cached_json = helpers.get("get_cached_json")
    set_cached_json = helpers.get("set_cached_json")
    get_snapshot_payload = helpers.get("get_snapshot_payload")

    def _cache_key(name: str, *, version: int = 1) -> str:
        args = {key: request.args.getlist(key) for key in sorted(request.args.keys())}
        return json.dumps({"name": name, "v": version, "args": args}, sort_keys=True, ensure_ascii=True)

    def _cached_quant_payload(namespace: str, cache_key: str, ttl_seconds: int, builder, *, snapshot: bool = False):
        if snapshot and callable(get_snapshot_payload):
            return get_snapshot_payload(namespace, cache_key, builder, ttl_seconds=ttl_seconds)
        if callable(get_cached_json):
            cached = get_cached_json(namespace, cache_key)
            if isinstance(cached, dict):
                return cached
        payload = builder()
        if callable(set_cached_json):
            set_cached_json(namespace, cache_key, payload, ttl_seconds)
        return payload

    def _load_persistent_tile(cache_key: str) -> dict[str, Any] | None:
        try:
            with postgres_connection(PostgresSettings(), readonly=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT payload
                        FROM quant.quant_price_series_tiles
                        WHERE tile_key = %s
                          AND (expires_at IS NULL OR expires_at > now())
                        LIMIT 1
                        """,
                        (cache_key,),
                    )
                    row = cur.fetchone()
        except Exception:
            return None
        payload = row.get("payload") if row else None
        return payload if isinstance(payload, dict) else None

    @bp.route("/markets", methods=["GET"])
    def api_quant_price_markets():
        limit = min(max(_parse_int_arg("limit", 50) or 50, 1), 200)
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            rows = get_quant_price_markets(
                conn,
                search=(request.args.get("q") or "").strip() or None,
                token_side=(request.args.get("token_side") or "").strip() or None,
                limit=limit,
            )
        return jsonify({"items": [_camel_row(row) for row in rows], "count": len(rows)})

    @bp.route("/events", methods=["GET"])
    def api_quant_price_events():
        limit = min(max(_parse_int_arg("limit", 50) or 50, 1), 200)
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            rows = get_quant_price_events(
                conn,
                search=(request.args.get("q") or "").strip() or None,
                limit=limit,
            )
        return jsonify({"items": [_camel_row(row) for row in rows], "count": len(rows)})

    @bp.route("/frontend-prices", methods=["GET"])
    def api_quant_frontend_prices():
        limit = min(max(_parse_int_arg("limit", 1000) or 1000, 1), 25000)
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            rows = get_frontend_prices(
                conn,
                market_slug=(request.args.get("market_slug") or "").strip() or None,
                token_side=(request.args.get("token_side") or "").strip() or None,
                token_id=(request.args.get("token_id") or "").strip() or None,
                from_ts=_parse_time_arg("from"),
                to_ts=_parse_time_arg("to"),
                limit=limit,
            )
        return jsonify({"items": [_camel_row(row) for row in rows], "count": len(rows), "source": "frontend"})

    @bp.route("/block-close-prices", methods=["GET"])
    def api_quant_block_close_prices():
        limit = min(max(_parse_int_arg("limit", 1000) or 1000, 1), 25000)
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            rows = get_block_close_prices(
                conn,
                market_slug=(request.args.get("market_slug") or "").strip() or None,
                token_side=(request.args.get("token_side") or "").strip() or None,
                token_id=(request.args.get("token_id") or "").strip() or None,
                from_block=_parse_int_arg("from_block"),
                to_block=_parse_int_arg("to_block"),
                limit=limit,
            )
        return jsonify({"items": [_camel_row(row) for row in rows], "count": len(rows), "source": "orderfilled_block_close"})

    @bp.route("/market-price-series", methods=["GET"])
    def api_quant_market_price_series():
        market_slug = (request.args.get("market_slug") or "").strip()
        if not market_slug:
            return jsonify({"error": "market_slug is required"}), 400
        limit = min(max(_parse_int_arg("limit", 2500) or 2500, 1), 25000)
        max_outcomes = min(max(_parse_int_arg("max_outcomes", 24) or 24, 1), 100)
        price_source = (request.args.get("price_source") or request.args.get("source") or "orderfilled_block_close").strip()
        point_format = (request.args.get("point_format") or "lite").strip().lower()
        scope = (request.args.get("scope") or "auto").strip().lower()
        cache_key = _cache_key("market-price-series", version=2)

        def build_payload() -> dict[str, Any]:
            with postgres_connection(PostgresSettings(), readonly=True) as conn:
                payload = get_market_price_series(
                    conn,
                    market_slug=market_slug,
                    price_source=price_source,
                    scope=scope,
                    token_side=(request.args.get("token_side") or "").strip() or None,
                    from_ts=_parse_time_arg("from"),
                    to_ts=_parse_time_arg("to"),
                    from_block=_parse_int_arg("from_block"),
                    to_block=_parse_int_arg("to_block"),
                    limit=limit,
                    max_outcomes=max_outcomes,
                )
            return _camel_row(_apply_point_payload_format(payload, point_format))

        return jsonify(_cached_quant_payload("quant-market-series", cache_key, 12, build_payload))

    @bp.route("/event-price-series", methods=["GET"])
    def api_quant_event_price_series():
        event_slug = (request.args.get("event_slug") or request.args.get("market_slug") or "").strip()
        if not event_slug:
            return jsonify({"error": "event_slug is required"}), 400
        limit = min(max(_parse_int_arg("limit", 2500) or 2500, 1), 25000)
        max_outcomes = min(max(_parse_int_arg("max_outcomes", 100) or 100, 1), 200)
        price_source = (request.args.get("price_source") or request.args.get("source") or "orderfilled_block_close").strip()
        point_format = (request.args.get("point_format") or "lite").strip().lower()
        cache_key = _cache_key("event-price-series", version=2)

        def build_payload() -> dict[str, Any]:
            with postgres_connection(PostgresSettings(), readonly=True) as conn:
                payload = get_event_price_series(
                    conn,
                    event_slug=event_slug,
                    price_source=price_source,
                    from_ts=_parse_time_arg("from"),
                    to_ts=_parse_time_arg("to"),
                    from_block=_parse_int_arg("from_block"),
                    to_block=_parse_int_arg("to_block"),
                    limit=limit,
                    max_outcomes=max_outcomes,
                )
            return _camel_row(_apply_point_payload_format(payload, point_format))

        return jsonify(_cached_quant_payload("quant-event-series", cache_key, 12, build_payload))

    @bp.route("/event-price-tile", methods=["GET"])
    def api_quant_event_price_tile():
        event_slug = (request.args.get("event_slug") or request.args.get("market_slug") or "").strip()
        if not event_slug:
            return jsonify({"error": "event_slug is required"}), 400
        limit = min(max(_parse_int_arg("limit", 2500) or 2500, 1), 25000)
        max_outcomes = min(max(_parse_int_arg("max_outcomes", 100) or 100, 1), 200)
        max_points = min(max(_parse_int_arg("max_points", 600) or 600, 50), 2500)
        top_n = min(max(_parse_int_arg("top_n", 12) or 12, 1), max_outcomes)
        price_source = (request.args.get("price_source") or request.args.get("source") or "orderfilled_block_close").strip()
        point_format = (request.args.get("point_format") or "lite").strip().lower()
        tile_range = (request.args.get("range") or "latest").strip().lower()
        resolution = (request.args.get("resolution") or "auto").strip().lower()
        cache_key = _cache_key("event-price-tile", version=1)

        def build_payload() -> dict[str, Any]:
            persisted = _load_persistent_tile(cache_key)
            if persisted is not None:
                return persisted
            with postgres_connection(PostgresSettings(), readonly=True) as conn:
                payload = get_event_price_tile(
                    conn,
                    event_slug=event_slug,
                    price_source=price_source,
                    from_ts=_parse_time_arg("from"),
                    to_ts=_parse_time_arg("to"),
                    from_block=_parse_int_arg("from_block"),
                    to_block=_parse_int_arg("to_block"),
                    limit=limit,
                    max_outcomes=max_outcomes,
                    top_n=top_n,
                    max_points=max_points,
                    tile_range=tile_range,
                    resolution=resolution,
                )
            return _camel_row(_apply_point_payload_format(payload, point_format))

        return jsonify(_cached_quant_payload("quant-event-tile", cache_key, 45, build_payload, snapshot=True))

    @bp.route("/event-price-stream", methods=["GET"])
    def api_quant_event_price_stream():
        event_slug = (request.args.get("event_slug") or request.args.get("market_slug") or "").strip()
        if not event_slug:
            return jsonify({"error": "event_slug is required"}), 400
        price_source = (request.args.get("price_source") or request.args.get("source") or "orderfilled_block_close").strip()
        interval_seconds = min(max(_parse_int_arg("interval", 5) or 5, 2), 60)
        max_outcomes = min(max(_parse_int_arg("max_outcomes", 24) or 24, 1), 100)

        def build_latest_payload() -> dict[str, Any]:
            with postgres_connection(PostgresSettings(), readonly=True) as conn:
                payload = get_event_price_tile(
                    conn,
                    event_slug=event_slug,
                    price_source=price_source,
                    limit=1,
                    max_outcomes=max_outcomes,
                    top_n=max_outcomes,
                    max_points=50,
                    tile_range="latest",
                    resolution="latest",
                )
            payload = _camel_row(_apply_point_payload_format(payload, "lite"))
            return {
                "eventSlug": event_slug,
                "priceSource": price_source,
                "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "outcomes": [
                    {
                        "tokenId": outcome.get("tokenId"),
                        "outcomeLabel": outcome.get("outcomeLabel"),
                        "buyYesPrice": outcome.get("buyYesPrice"),
                        "buyNoPrice": outcome.get("buyNoPrice"),
                        "latestPrice": outcome.get("latestPrice"),
                        "lastX": outcome.get("lastX"),
                        "rows": outcome.get("rows"),
                    }
                    for outcome in payload.get("outcomes") or []
                ],
            }

        @stream_with_context
        def generate():
            last_serialized = ""
            while True:
                try:
                    serialized = json.dumps(build_latest_payload(), ensure_ascii=True, default=str)
                    if serialized != last_serialized:
                        last_serialized = serialized
                        yield f"event: price\\ndata: {serialized}\\n\\n"
                    else:
                        yield ": keepalive\\n\\n"
                except GeneratorExit:
                    return
                except Exception as exc:
                    serialized_error = json.dumps({"error": str(exc), "eventSlug": event_slug}, ensure_ascii=True)
                    yield f"event: error\\ndata: {serialized_error}\\n\\n"
                time.sleep(interval_seconds)

        return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @bp.route("/price-build-status", methods=["GET"])
    def api_quant_price_build_status():
        limit = min(max(_parse_int_arg("limit", 100) or 100, 1), 1000)
        source = (request.args.get("source") or "").strip() or None
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            rows = get_price_build_status(conn, source=source, limit=limit)
        return jsonify({"items": [_camel_row(row) for row in rows], "count": len(rows)})

    @bp.route("/backtest-runs", methods=["POST"])
    def api_quant_create_backtest_run():
        payload = request.get_json(silent=True) or {}
        try:
            with postgres_connection(PostgresSettings(), readonly=False) as conn:
                create_schema(conn)
                run_id = create_backtest_run(conn, payload)
            with postgres_connection(PostgresSettings(), readonly=True) as conn:
                row = get_backtest_run(conn, run_id=run_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
        if not row:
            return jsonify({"error": "backtest run not found"}), 500
        return jsonify({"item": _camel_row(row), "runId": row.get("run_id"), "status": row.get("status")}), 202

    @bp.route("/backtest-runs/<int:run_id>", methods=["GET"])
    def api_quant_get_backtest_run(run_id: int):
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            row = get_backtest_run(conn, run_id=run_id)
        if not row:
            return jsonify({"error": "backtest run not found"}), 404
        return jsonify({"item": _camel_row(row)})

    @bp.route("/backtest-runs/<int:run_id>/trades", methods=["GET"])
    def api_quant_get_backtest_trades(run_id: int):
        limit = min(max(_parse_int_arg("limit", 1000) or 1000, 1), 25000)
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            rows = get_backtest_trades(conn, run_id=run_id, limit=limit)
        return jsonify({"items": [_camel_row(row) for row in rows], "count": len(rows)})

    @bp.route("/backtest-runs/<int:run_id>/equity", methods=["GET"])
    def api_quant_get_backtest_equity(run_id: int):
        limit = min(max(_parse_int_arg("limit", 25000) or 25000, 1), 25000)
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            rows = get_backtest_equity(conn, run_id=run_id, limit=limit)
        return jsonify({"items": [_camel_row(row) for row in rows], "count": len(rows)})

    @bp.route("/backtest-runs/<int:run_id>/metrics", methods=["GET"])
    def api_quant_get_backtest_metrics(run_id: int):
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            rows = get_backtest_metrics(conn, run_id=run_id)
        return jsonify({"items": [_camel_row(row) for row in rows], "count": len(rows)})

    return bp
