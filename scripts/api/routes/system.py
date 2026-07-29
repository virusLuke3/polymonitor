from __future__ import annotations

import hmac
import os

from flask import Blueprint, jsonify, request

from scripts.api.services import system_service


def _operations_authorized() -> bool:
    configured = os.environ.get("POLYDATA_OPERATIONS_API_TOKEN", "")
    supplied = request.headers.get("Authorization", "")
    if configured:
        expected = f"Bearer {configured}"
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
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


def create_system_blueprint(helpers: dict) -> Blueprint:
    bp = Blueprint("system_routes", __name__)

    @bp.route("/system/health", methods=["GET"])
    def api_system_health():
        if not _operations_authorized():
            return _authorization_error()
        return jsonify(helpers["build_system_health_payload"]())

    @bp.route("/system/seed-health", methods=["GET"])
    @bp.route("/runtime/system/seed-health", methods=["GET"])
    def api_seed_health():
        if not _operations_authorized():
            return _authorization_error()
        return jsonify(helpers["build_seed_health_payload"]())

    @bp.route("/system/operations", methods=["GET"])
    def api_operations():
        if not _operations_authorized():
            return _authorization_error()
        return jsonify(system_service.build_operations_payload())

    @bp.route("/system/incidents", methods=["GET"])
    def api_operations_incidents():
        if not _operations_authorized():
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
            redis_ready = bool(helpers["get_redis_client"]())
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
