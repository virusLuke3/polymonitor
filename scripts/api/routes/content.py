from __future__ import annotations

import os

from flask import Blueprint, jsonify, request


def _publish_latest_content(payload: dict) -> None:
    try:
        from telegram.topics.runtime_bridge import publish_panel_snapshot
    except Exception:
        return
    try:
        publish_panel_snapshot("latest-content", payload)
    except Exception:
        return


def _publish_related_content(payload: dict) -> None:
    try:
        from telegram.topics.runtime_bridge import publish_panel_snapshot
    except Exception:
        return
    try:
        publish_panel_snapshot("related-news", payload)
    except Exception:
        return


def _runtime_content_fallback(limit: int, *, market_id: int | None = None, helpers: dict) -> dict:
    enabled = str(os.environ.get("POLYDATA_CONTENT_API_REFRESH_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        payload = {"items": [], "sourceMode": "database-empty", "degraded": True}
    else:
        payload = helpers["get_runtime_content_latest"](limit=limit)
        payload["sourceMode"] = f"{payload.get('sourceMode') or 'runtime-rss'}:db-fallback"
        payload["degraded"] = True
    if market_id is not None:
        payload["marketId"] = market_id
    return payload


def create_content_blueprint(helpers: dict) -> Blueprint:
    bp = Blueprint("content_routes", __name__)

    @bp.route("/content/market/<int:market_id>", methods=["GET"])
    def api_content_by_market_id(market_id: int):
        limit = min(20, max(1, int(request.args.get("limit", 8))))
        try:
            market = helpers["get_market_by_id"](market_id)
            if not market:
                return jsonify({"error": "Market not found", "marketId": market_id}), 404
            payload = helpers["get_related_content_payload"](market_id, limit=limit)
            payload = {
                **payload,
                "marketTitle": market.get("title"),
                "marketSlug": market.get("slug"),
                "marketCategory": market.get("category"),
            }
            _publish_related_content(payload)
            return jsonify(payload)
        except Exception:
            return jsonify(_runtime_content_fallback(limit, market_id=market_id, helpers=helpers))

    @bp.route("/content/latest", methods=["GET"])
    def api_content_latest():
        limit = min(20, max(1, int(request.args.get("limit", 8))))
        try:
            payload = helpers["get_latest_content_payload"](limit=limit)
        except Exception:
            payload = _runtime_content_fallback(limit, helpers=helpers)
        _publish_latest_content(payload)
        return jsonify(payload)

    return bp
