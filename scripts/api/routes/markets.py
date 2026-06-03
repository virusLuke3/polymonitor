from __future__ import annotations

from flask import Blueprint, jsonify, request


def create_markets_blueprint(helpers: dict) -> Blueprint:
    bp = Blueprint("market_routes", __name__)

    @bp.route("/markets", methods=["GET"])
    def api_markets():
        status = (request.args.get("status") or "active").strip().lower()
        query = (request.args.get("q") or "").strip()
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(500, max(1, int(request.args.get("pageSize", 20))))
        return jsonify(helpers["get_markets_payload"](status=status, query=query, page=page, page_size=page_size))

    @bp.route("/markets/<int:market_id>", methods=["GET"])
    def api_market_by_id(market_id: int):
        market = helpers["get_market_by_id"](market_id)
        if not market:
            return jsonify({"error": "Market not found", "marketId": market_id}), 404
        return jsonify(helpers["normalize_market"](market))

    @bp.route("/markets/<int:market_id>/trades", methods=["GET"])
    def api_market_trades_by_id(market_id: int):
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(0, int(request.args.get("offset", 0)))
        return jsonify(helpers["get_trades_by_market_id"](market_id, limit=limit, offset=offset))

    @bp.route("/trades/recent", methods=["GET"])
    def api_recent_trades():
        limit = min(int(request.args.get("limit", 24)), 200)
        return jsonify(helpers["get_recent_trades_snapshot"](limit=limit))

    @bp.route("/markets/<int:market_id>/oracle", methods=["GET"])
    def api_market_oracle_by_id(market_id: int):
        payload = helpers["get_market_oracle_payload"](market_id)
        status_code = int(payload.pop("_status", 200))
        return jsonify(payload), status_code

    @bp.route("/oracle/recent", methods=["GET"])
    def api_recent_oracle():
        limit = min(int(request.args.get("limit", 24)), 200)
        return jsonify(helpers["get_recent_oracle_snapshot"](limit=limit))

    @bp.route("/markets/<int:market_id>/price", methods=["GET"])
    def api_market_price_by_id(market_id: int):
        payload = helpers["get_market_detail_payload"](market_id)
        status_code = int(payload.get("_status", 200))
        if status_code >= 400:
            return jsonify(payload), status_code
        price = payload.get("price") if isinstance(payload, dict) else None
        return jsonify(price or {"marketId": market_id, "localMarketId": market_id})

    @bp.route("/markets/<int:market_id>/chart", methods=["GET"])
    def api_market_chart_by_id(market_id: int):
        range_name = (request.args.get("range") or "1d").strip().lower()
        interval = (request.args.get("interval") or "5m").strip().lower()
        return jsonify(helpers["get_market_chart_payload"](market_id, range_name=range_name, interval=interval))

    @bp.route("/markets/<int:market_id>/detail", methods=["GET"])
    def api_market_detail_by_id(market_id: int):
        payload = helpers["get_market_detail_payload"](market_id)
        status_code = int(payload.pop("_status", 200))
        return jsonify(payload), status_code

    @bp.route("/markets/<int:market_id>/workspace", methods=["GET"])
    def api_market_workspace_by_id(market_id: int):
        payload = helpers["get_market_workspace_payload"](market_id)
        status_code = int(payload.pop("_status", 200))
        return jsonify(payload), status_code

    @bp.route("/markets/<slug>", methods=["GET"])
    def api_market_detail(slug: str):
        slug = slug.strip()
        if not slug:
            return jsonify({"error": "slug required"}), 400
        market = helpers["get_market_by_slug"](slug)
        if not market:
            return jsonify({"error": "Market not found", "slug": slug}), 404
        return jsonify(helpers["normalize_market"](market))

    @bp.route("/markets/<slug>/trades", methods=["GET"])
    def api_market_trades(slug: str):
        slug = slug.strip()
        if not slug:
            return jsonify({"error": "slug required"}), 400
        market = helpers["get_market_by_slug"](slug)
        if not market:
            return jsonify({"error": "Market not found", "slug": slug}), 404
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(0, int(request.args.get("offset", 0)))
        return jsonify(helpers["get_trades_by_market_id"](market["id"], limit=limit, offset=offset))

    return bp
