from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import Blueprint, jsonify, request

from scripts.api.services import system_service


def _operations_authorized(helpers: Mapping[str, Any]) -> bool:
    authenticate_request = helpers.get("authenticate_request")
    if callable(authenticate_request):
        authenticate_request(
            request,
            required_role="admin",
            required_scope="operations:read",
        )
        return True
    forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP")
    return not forwarded and request.remote_addr in {"127.0.0.1", "::1"}


def _authorization_error():
    response = jsonify(
        {
            "status": "unauthorized",
            "requiredScope": "operations:read",
        }
    )
    response.status_code = 401
    response.headers["WWW-Authenticate"] = 'Bearer realm="polymonitor-operations", scope="operations:read"'
    return response


def create_system_blueprint(helpers: Mapping[str, Any]) -> Blueprint:
    bp = Blueprint("system_routes", __name__)

    @bp.route("/system/health", methods=["GET"])
    def api_system_health():
        if not _operations_authorized(helpers):
            return _authorization_error()
        return jsonify(helpers["build_system_health_payload"]())

    @bp.route("/system/seed-health", methods=["GET"])
    @bp.route("/runtime/system/seed-health", methods=["GET"])
    def api_seed_health():
        if not _operations_authorized(helpers):
            return _authorization_error()
        return jsonify(helpers["build_seed_health_payload"]())

    @bp.route("/system/operations", methods=["GET"])
    def api_operations():
        if not _operations_authorized(helpers):
            return _authorization_error()
        return jsonify(system_service.build_operations_payload())

    @bp.route("/system/incidents", methods=["GET"])
    def api_operations_incidents():
        if not _operations_authorized(helpers):
            return _authorization_error()
        return jsonify(system_service.build_incidents_payload())

    @bp.route("/health", methods=["GET"])
    def health():
        database_ready = False
        redis_ready = False
        try:
            database_ready = bool(helpers["table_exists"]("sync_state"))
        except Exception:
            database_ready = False
        try:
            redis_client = helpers["get_redis_client"]()
            ping = getattr(redis_client, "ping", None)
            redis_ready = bool(ping()) if callable(ping) else bool(redis_client)
        except Exception:
            redis_ready = False
        return jsonify(
            {
                "status": "ok" if database_ready and redis_ready else "degraded",
                "database": database_ready,
                "redis": redis_ready,
                "generatedAt": system_service.utc_now_iso(),
            }
        )

    return bp
