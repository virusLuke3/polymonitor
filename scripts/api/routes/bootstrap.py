from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, request
from api.services.free_content.public import filter_bootstrap


@dataclass(frozen=True)
class BootstrapRouteDependencies:
    get_dashboard_payload_cached: Callable[[], Any]
    get_bootstrap_payload_cached: Callable[[], Any]
    search_markets: Callable[..., Any]


def create_bootstrap_blueprint(dependencies: BootstrapRouteDependencies) -> Blueprint:
    bp = Blueprint("bootstrap_routes", __name__)

    @bp.route("/dashboard", methods=["GET"])
    def api_dashboard():
        return jsonify(dependencies.get_dashboard_payload_cached())

    @bp.route("/bootstrap", methods=["GET"])
    def api_bootstrap():
        return jsonify(filter_bootstrap(dependencies.get_bootstrap_payload_cached()))

    @bp.route("/search", methods=["GET"])
    def api_search():
        query = request.args.get("q") or ""
        limit = min(50, max(1, int(request.args.get("limit", 10))))
        return jsonify(dependencies.search_markets(query, limit=limit))

    return bp
