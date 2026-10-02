from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, request


@dataclass(frozen=True)
class SystemRouteDependencies:
    authenticate_request: Callable[..., Any]
    build_system_health_payload: Callable[[], Any]
    build_seed_health_payload: Callable[[], Any]
    describe_db_target: Callable[[], str]
    get_redis_client: Callable[[], Any]


def create_system_blueprint(dependencies: SystemRouteDependencies) -> Blueprint:
    bp = Blueprint("system_routes", __name__)

    @bp.route("/system/health", methods=["GET"])
    def api_system_health():
        dependencies.authenticate_request(request, required_role="admin", required_scope="operations:read")
        return jsonify(dependencies.build_system_health_payload())

    @bp.route("/system/seed-health", methods=["GET"])
    @bp.route("/runtime/system/seed-health", methods=["GET"])
    def api_seed_health():
        dependencies.authenticate_request(request, required_role="admin", required_scope="operations:read")
        return jsonify(dependencies.build_seed_health_payload())

    @bp.route("/health/live", methods=["GET"])
    def liveness():
        # No database, Redis, or upstream work on the process liveness path.
        return jsonify({"status": "ok"})

    @bp.route("/health", methods=["GET"])
    def health():
        try:
            database_ready = bool(dependencies.describe_db_target())
        except Exception:
            database_ready = False
        try:
            client = dependencies.get_redis_client()
            redis_ready = bool(client and client.ping())
        except Exception:
            redis_ready = False
        return jsonify(
            {
                "status": "ok" if database_ready and redis_ready else "degraded",
                "database": database_ready,
                "redis": redis_ready,
            }
        )

    return bp
