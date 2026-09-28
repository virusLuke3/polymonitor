"""HTTP request logging, CORS and error responses."""

from __future__ import annotations

import time
import uuid

from flask import g, jsonify, request
from werkzeug.exceptions import HTTPException

from api.services import auth_service


def register_http_hooks(app, allowed_origins):
    ALLOWED_ORIGINS = allowed_origins

    @app.before_request
    def log_request_start() -> None:
        g.request_started_at = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        app.logger.info(
            "request-start request_id=%s method=%s path=%s query=%s remote=%s",
            g.request_id,
            request.method,
            request.path,
            request.query_string.decode("utf-8", errors="replace"),
            request.headers.get("X-Forwarded-For", request.remote_addr),
        )

    @app.after_request
    def log_request_end(response):
        request_id = getattr(g, "request_id", "-")
        started_at = getattr(g, "request_started_at", None)
        duration_ms = (time.perf_counter() - started_at) * 1000 if started_at else -1
        response.headers["X-Request-ID"] = request_id
        origin = request.headers.get("Origin", "").strip()
        if origin and origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Accept, X-Requested-With, X-CSRF-Token, Authorization"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if (
            request.path == "/mcp"
            or request.path.startswith("/auth/")
            or request.path.startswith("/product/")
            or request.path.startswith("/briefings/")
            or request.path.startswith("/system/")
            or request.path.startswith("/runtime/system/")
        ):
            response.headers["Cache-Control"] = "no-store"
        app.logger.info(
            "request-end request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
            request_id,
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        request_id = getattr(g, "request_id", "-")
        app.logger.warning(
            "http-error request_id=%s method=%s path=%s status=%s detail=%s",
            request_id,
            request.method,
            request.path,
            getattr(error, "code", 500),
            getattr(error, "description", str(error)),
        )
        return (
            jsonify({"error": getattr(error, "description", "HTTP error"), "requestId": request_id}),
            getattr(error, "code", 500),
        )

    @app.errorhandler(auth_service.AuthError)
    def handle_auth_error(error: auth_service.AuthError):
        request_id = getattr(g, "request_id", "-")
        app.logger.warning(
            "auth-error request_id=%s method=%s path=%s status=%s code=%s",
            request_id,
            request.method,
            request.path,
            error.status_code,
            error.code,
        )
        response = jsonify({"error": {"code": error.code, "message": error.message}, "requestId": request_id})
        response.status_code = error.status_code
        if error.retry_after:
            response.headers["Retry-After"] = str(error.retry_after)
        if error.status_code == 401:
            response.headers["WWW-Authenticate"] = 'Bearer realm="polymonitor"'
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error: Exception):
        request_id = getattr(g, "request_id", "-")
        app.logger.exception(
            "unhandled-error request_id=%s method=%s path=%s error=%s", request_id, request.method, request.path, error
        )
        return (jsonify({"error": "Internal server error", "requestId": request_id}), 500)
