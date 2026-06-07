from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

from flask import Blueprint, jsonify, request


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.api.read_api import (  # noqa: E402
    get_backtest_equity,
    get_backtest_metrics,
    get_backtest_run,
    get_backtest_trades,
    get_block_close_prices,
    get_frontend_prices,
    get_price_build_status,
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
        "condition_id": "conditionId",
        "end_date": "endDate",
    }
    return {mapping.get(key, key): _json_value(value) for key, value in row.items()}


def create_quant_blueprint(_: dict) -> Blueprint:
    bp = Blueprint("quant_routes", __name__, url_prefix="/quant")

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
