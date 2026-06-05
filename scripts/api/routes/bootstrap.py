from __future__ import annotations

from flask import Blueprint, jsonify, request


def create_bootstrap_blueprint(helpers: dict) -> Blueprint:
    bp = Blueprint("bootstrap_routes", __name__)

    @bp.route("/dashboard", methods=["GET"])
    def api_dashboard():
        return jsonify(helpers["get_dashboard_payload_cached"]())

    @bp.route("/bootstrap", methods=["GET"])
    def api_bootstrap():
        return jsonify(helpers["get_bootstrap_payload_cached"]())

    @bp.route("/search", methods=["GET"])
    def api_search():
        query = request.args.get("q") or ""
        limit = min(50, max(1, int(request.args.get("limit", 10))))
        return jsonify(helpers["search_markets"](query, limit=limit))

    return bp
