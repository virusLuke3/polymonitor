from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, request


@dataclass(frozen=True)
class MarketGroupRouteDependencies:
    get_market_groups_payload: Callable[..., dict[str, Any]]
    get_market_group_detail_payload: Callable[[str], dict[str, Any] | None]
    get_market_group_chart_payload: Callable[..., dict[str, Any] | None]


def create_market_groups_blueprint(dependencies: MarketGroupRouteDependencies) -> Blueprint:
    bp = Blueprint("market_group_routes", __name__)

    @bp.errorhandler(ValueError)
    def invalid(_error):
        return jsonify({"status": "invalid", "error": "Invalid market group parameters"}), 400

    @bp.errorhandler(TimeoutError)
    def unavailable(_error):
        return respond({"status": "unavailable"})

    def respond(payload):
        response = jsonify(payload)
        response.status_code = int(payload.get("_status", 503 if payload.get("status") in {"unavailable", "warming"} else 200))
        response.headers["Cache-Control"] = "no-store"
        if response.status_code == 503:
            response.headers["Retry-After"] = "15"
        return response

    @bp.route("/market-groups", methods=["GET"])
    def api_market_groups():
        query = (request.args.get("q") or "").strip()
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(1, int(request.args.get("pageSize", 80))))
        sort = (request.args.get("sort") or "active").strip().lower()
        return respond(
            dependencies.get_market_groups_payload(
                query=query,
                page=page,
                page_size=page_size,
                sort=sort,
            )
        )

    @bp.route("/market-groups/<event_id>/detail", methods=["GET"])
    def api_market_group_detail(event_id: str):
        payload = dependencies.get_market_group_detail_payload(event_id)
        if not payload:
            return jsonify({"error": "market group not found", "eventId": event_id}), 404
        return respond(payload)

    @bp.route("/market-groups/<event_id>/chart", methods=["GET"])
    def api_market_group_chart(event_id: str):
        range_name = (request.args.get("range") or "1d").strip().lower()
        payload = dependencies.get_market_group_chart_payload(event_id, range_name=range_name)
        if not payload:
            return jsonify({"error": "market group chart unavailable", "eventId": event_id, "range": range_name}), 404
        return respond(payload)

    return bp
