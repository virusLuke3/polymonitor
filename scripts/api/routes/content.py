from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, request
import logging
from api.services.free_content.public import filter_payload
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContentRouteDependencies:
    get_market_by_id: Callable[[int], dict[str, Any] | None]
    get_related_content_payload: Callable[..., dict[str, Any]]
    get_latest_content_payload: Callable[..., dict[str, Any]]
    get_runtime_content_latest: Callable[..., dict[str, Any]]


def _publish_latest_content(payload: dict) -> None:
    if request.headers.get("X-PolyData-Telegram-Publisher") == "1":
        return
    try:
        from telegram.topics.runtime_bridge import publish_panel_snapshot
    except Exception:
        return
    try:
        publish_panel_snapshot("latest-content", payload)
    except Exception:
        return


def _publish_related_content(payload: dict) -> None:
    if request.headers.get("X-PolyData-Telegram-Publisher") == "1":
        return
    try:
        from telegram.topics.runtime_bridge import publish_panel_snapshot
    except Exception:
        return
    try:
        publish_panel_snapshot("related-news", payload)
    except Exception:
        return


def _runtime_content_fallback(
    limit: int,
    *,
    dependencies: ContentRouteDependencies,
    market_id: int | None = None,
) -> dict:
    # A public read must never trigger external acquisition or substitute global data.
    return {"items": [], "count": 0, "scope": "market" if market_id is not None else "global",
            "marketId": market_id, "market_id": market_id, "sourceMode": "database:free-public",
            "status": "unavailable", "empty_reason": "source_or_database_unavailable", "degraded": True,
            "window": {"days": 30 if request.args.get("days") == "30" else 7}}


def _content_response(payload):
    result = filter_payload(payload)
    unavailable = result.get("status") == "unavailable" and not result.get("items")
    response = jsonify(result)
    response.status_code = 503 if unavailable else 200
    # Never let a browser/CDN pin a transient failure or hide the next seed refresh.
    response.headers["Cache-Control"] = "no-store"
    if unavailable:
        response.headers["Retry-After"] = "30"
    return response


def create_content_blueprint(dependencies: ContentRouteDependencies) -> Blueprint:
    bp = Blueprint("content_routes", __name__)

    @bp.route("/content/market/<int:market_id>", methods=["GET"])
    def api_content_by_market_id(market_id: int):
        limit = min(20, max(1, int(request.args.get("limit", 8))))
        try:
            market = dependencies.get_market_by_id(market_id)
            if not market:
                return jsonify({"error": "Market not found", "marketId": market_id}), 404
            payload = dependencies.get_related_content_payload(
                market_id, limit=limit, days=30 if request.args.get("days")=="30" else 7, market=market
            )
            payload = {
                **payload,
                "marketTitle": market.get("title"),
                "marketSlug": market.get("slug"),
                "marketCategory": market.get("category"),
            }
            return _content_response(payload)
        except Exception as exc:
            logger.warning("Market content read failed: %s", type(exc).__name__)
            return _content_response(
                _runtime_content_fallback(
                    limit,
                    dependencies=dependencies,
                    market_id=market_id,
                )
            )

    @bp.route("/content/latest", methods=["GET"])
    def api_content_latest():
        limit = min(20, max(1, int(request.args.get("limit", 8))))
        try:
            payload = dependencies.get_latest_content_payload(limit=limit, days=30 if request.args.get("days")=="30" else 7)
        except Exception as exc:
            logger.warning("Global content read failed: %s", type(exc).__name__)
            payload = _runtime_content_fallback(limit, dependencies=dependencies)
        return _content_response(payload)

    return bp
