from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, request

from api.services import outcome_semantics_service


@dataclass(frozen=True)
class MarketRouteDependencies:
    get_markets_payload: Callable[..., dict[str, Any]]
    get_market_by_id: Callable[[int], dict[str, Any] | None]
    get_market_by_slug: Callable[[str], dict[str, Any] | None]
    normalize_market: Callable[[dict[str, Any]], dict[str, Any]]
    get_trades_by_market_id: Callable[..., Any]
    get_recent_trades_snapshot: Callable[..., Any]
    get_market_oracle_payload: Callable[[int], dict[str, Any]]
    get_recent_oracle_snapshot: Callable[..., Any]
    get_market_detail_payload: Callable[[int], dict[str, Any]]
    get_market_chart_payload: Callable[..., Any]
    get_market_workspace_payload: Callable[[int], dict[str, Any]]
    sanitize_payload: Callable[..., Any]
    get_market_focus_tile_payload: Callable[[int], dict[str, Any]]


def create_markets_blueprint(dependencies: MarketRouteDependencies) -> Blueprint:
    bp = Blueprint("market_routes", __name__)

    @bp.errorhandler(TimeoutError)
    def unavailable(_error):
        return jsonify({"status": "unavailable", "error": "Market data temporarily unavailable"}), 503

    def sanitize(payload: Any, *, market_id: int | None = None) -> Any:
        return dependencies.sanitize_payload(
            payload,
            market_id=market_id,
        )

    @bp.route("/markets", methods=["GET"])
    def api_markets():
        status = (request.args.get("status") or "active").strip().lower()
        query = (request.args.get("q") or "").strip()
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(500, max(1, int(request.args.get("pageSize", 20))))
        return jsonify(
            sanitize(
                dependencies.get_markets_payload(
                    status=status,
                    query=query,
                    page=page,
                    page_size=page_size,
                )
            )
        )

    @bp.route("/markets/<int:market_id>", methods=["GET"])
    def api_market_by_id(market_id: int):
        market = dependencies.get_market_by_id(market_id)
        if not market:
            return jsonify({"error": "Market not found", "marketId": market_id}), 404
        normalized = outcome_semantics_service.bind_trusted_oracle_logical_fields(dependencies.normalize_market(market))
        return jsonify(sanitize(normalized, market_id=market_id))

    @bp.route("/markets/<int:market_id>/trades", methods=["GET"])
    def api_market_trades_by_id(market_id: int):
        try:
            limit = min(max(int(request.args.get("limit", 100)), 1), 500)
            offset = max(0, int(request.args.get("offset", 0)))
            if offset > 5000:
                raise ValueError("Use before=block:log:tx_hash for deeper pagination")
            cursor = {}
            if request.args.get("before"):
                block, log, tx = request.args["before"].split(":")
                block, log, tx = int(block), int(log), tx.lower().removeprefix("0x")
                if block < 0 or log < 0 or len(tx) != 64 or any(c not in "0123456789abcdef" for c in tx):
                    raise ValueError("Invalid trade cursor")
                if offset:
                    raise ValueError("Use either before or offset")
                cursor["before"] = (block, log, tx)
        except ValueError:
            return jsonify({"error": "Invalid pagination; before must be block:log:tx_hash, offset at most 5000"}), 400
        return jsonify(
            sanitize(
                dependencies.get_trades_by_market_id(market_id, limit=limit, offset=offset, **cursor),
                market_id=market_id,
            )
        )

    @bp.route("/trades/recent", methods=["GET"])
    def api_recent_trades():
        limit = min(int(request.args.get("limit", 24)), 200)
        return jsonify(sanitize(dependencies.get_recent_trades_snapshot(limit=limit)))

    @bp.route("/markets/<int:market_id>/oracle", methods=["GET"])
    def api_market_oracle_by_id(market_id: int):
        payload = dependencies.get_market_oracle_payload(market_id)
        status_code = int(payload.pop("_status", 200))
        return jsonify(sanitize(payload, market_id=market_id)), status_code

    @bp.route("/oracle/recent", methods=["GET"])
    def api_recent_oracle():
        limit = min(int(request.args.get("limit", 24)), 200)
        return jsonify(sanitize(dependencies.get_recent_oracle_snapshot(limit=limit)))

    @bp.route("/markets/<int:market_id>/price", methods=["GET"])
    def api_market_price_by_id(market_id: int):
        payload = dependencies.get_market_detail_payload(market_id)
        status_code = int(payload.get("_status", 200))
        if status_code >= 400:
            return jsonify(payload), status_code
        price = payload.get("price") if isinstance(payload, dict) else None
        return jsonify(
            sanitize(
                price or {"marketId": market_id, "localMarketId": market_id},
                market_id=market_id,
            )
        )

    @bp.route("/markets/<int:market_id>/chart", methods=["GET"])
    def api_market_chart_by_id(market_id: int):
        range_name = (request.args.get("range") or "1d").strip().lower()
        interval = (request.args.get("interval") or "5m").strip().lower()
        return jsonify(
            sanitize(
                dependencies.get_market_chart_payload(
                    market_id,
                    range_name=range_name,
                    interval=interval,
                ),
                market_id=market_id,
            )
        )

    @bp.route("/markets/<int:market_id>/detail", methods=["GET"])
    def api_market_detail_by_id(market_id: int):
        payload = dependencies.get_market_detail_payload(market_id)
        status_code = int(payload.pop("_status", 200))
        return jsonify(sanitize(payload, market_id=market_id)), status_code

    @bp.route("/markets/<int:market_id>/workspace", methods=["GET"])
    def api_market_workspace_by_id(market_id: int):
        payload = dependencies.get_market_workspace_payload(market_id)
        status_code = int(payload.pop("_status", 200))
        return jsonify(sanitize(payload, market_id=market_id)), status_code

    @bp.route("/markets/<int:market_id>/focus-tile", methods=["GET"])
    def api_market_focus_tile_by_id(market_id: int):
        payload = dependencies.get_market_focus_tile_payload(market_id)
        status_code = int(payload.pop("_status", 200))
        return jsonify(sanitize(payload, market_id=market_id)), status_code

    @bp.route("/markets/<slug>", methods=["GET"])
    def api_market_detail(slug: str):
        slug = slug.strip()
        if not slug:
            return jsonify({"error": "slug required"}), 400
        market = dependencies.get_market_by_slug(slug)
        if not market:
            return jsonify({"error": "Market not found", "slug": slug}), 404
        return jsonify(
            sanitize(
                outcome_semantics_service.bind_trusted_oracle_logical_fields(dependencies.normalize_market(market)),
                market_id=int(market.get("id") or 0) or None,
            )
        )

    @bp.route("/markets/<slug>/trades", methods=["GET"])
    def api_market_trades(slug: str):
        slug = slug.strip()
        if not slug:
            return jsonify({"error": "slug required"}), 400
        market = dependencies.get_market_by_slug(slug)
        if not market:
            return jsonify({"error": "Market not found", "slug": slug}), 404
        return api_market_trades_by_id(int(market["id"]))

    return bp
