from __future__ import annotations

from flask import Blueprint, jsonify, make_response

from agent.market_wide.snapshot import normalize_lens, read_market_wide_quant_snapshot, read_market_wide_snapshot, snapshot_response


def create_agent_snapshot_blueprint(helpers: dict) -> Blueprint:
    bp = Blueprint("agent_snapshot_routes", __name__)

    @bp.route("/runtime/agent/market-wide-insights/<lens>", methods=["GET"])
    def api_market_wide_snapshot(lens: str):
        normalized_lens = normalize_lens(lens)
        snapshot = read_market_wide_snapshot(helpers, normalized_lens, allow_stale=True)
        if snapshot is None:
            return jsonify({"error": "agent-snapshot-missing", "status": "missing", "lens": normalized_lens}), 404
        response = make_response(jsonify(snapshot_response(snapshot)))
        response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=300"
        return response

    @bp.route("/runtime/agent/market-wide-quant/<lens>", methods=["GET"])
    def api_market_wide_quant_snapshot(lens: str):
        normalized_lens = normalize_lens(lens)
        snapshot = read_market_wide_quant_snapshot(helpers, normalized_lens, allow_stale=True)
        if snapshot is None:
            return jsonify({"error": "agent-quant-snapshot-missing", "status": "missing", "lens": normalized_lens}), 404
        response = make_response(jsonify(snapshot))
        response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=300"
        return response

    return bp
