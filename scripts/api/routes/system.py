from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, jsonify, request
from api.readiness import CachedProbe


@dataclass(frozen=True)
class SystemRouteDependencies:
    authenticate_request: Callable[..., Any]
    build_system_health_payload: Callable[[], Any]
    build_seed_health_payload: Callable[[], Any]
    describe_db_target: Callable[[], str]
    get_redis_client: Callable[[], Any]
    probe_database: Callable[[], Any] | None = None


def create_system_blueprint(dependencies: SystemRouteDependencies) -> Blueprint:
    bp = Blueprint("system_routes", __name__)
    database_probe = CachedProbe(dependencies.probe_database or (lambda: False))
    redis_probe = CachedProbe(lambda: bool((client := dependencies.get_redis_client()) and client.ping()))

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
            database_ready = database_probe()
        except Exception:
            database_ready = False
        try:
            redis_ready = redis_probe()
        except Exception:
            redis_ready = False
        response = jsonify(
            {
                "status": "ok" if database_ready and redis_ready else "degraded",
                "database": database_ready,
                "redis": redis_ready,
            }
        )
        response.status_code = 200 if database_ready and redis_ready else 503
        response.headers["Cache-Control"] = "no-store"
        if response.status_code == 503:
            response.headers["Retry-After"] = "15"
        return response

    return bp
