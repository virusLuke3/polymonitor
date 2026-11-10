"""HTTP request logging, CORS and error responses."""

from __future__ import annotations

import gzip
import time
import uuid

from flask import g, jsonify, request
from werkzeug.exceptions import HTTPException

from api.services import auth_service
from api.services.signal_reads import SignalReadPending
from api.runtime_panels import RUNTIME_PANEL_MODULES

# The registry contains public read-only snapshot routes, not auth/account/LOB
# or streaming endpoints. Use the shared contract instead of three special cases.
PUBLIC_LARGE_SNAPSHOTS = frozenset(panel.route for panel in RUNTIME_PANEL_MODULES) | frozenset({
    "/runtime/agent/market-wide-insights/overview",
    "/runtime/agent/market-wide-insights/special",
    "/runtime/agent/market-wide-insights/trend",
    "/content/latest",
})


def compress_public_snapshot(response):
    """Compress before the remote relay; preserve data and cache semantics."""
    if (request.method != "GET" or request.path not in PUBLIC_LARGE_SNAPSHOTS
            or response.status_code != 200 or response.mimetype != "application/json"
            or response.is_streamed or response.direct_passthrough
            or response.headers.get("Content-Encoding") or response.headers.get("Set-Cookie")):
        return response
    response.vary.add("Accept-Encoding")
    if request.accept_encodings.quality("gzip") <= 0:
        return response
    body = response.get_data()
    if len(body) < 1024:
        return response
    packed = gzip.compress(body, compresslevel=5, mtime=0)
    if len(packed) >= len(body):
        return response
    response.set_data(packed)
    response.headers["Content-Encoding"] = "gzip"
    etag, _weak = response.get_etag()
    if etag is not None:
        response.set_etag(etag, weak=True)
    return response


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
            response.vary.add("Origin")
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
        response = compress_public_snapshot(response)
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

    @app.errorhandler(SignalReadPending)
    def handle_signal_verification_pending(_error):
        response = jsonify(status="warming", errorCode="signal-verification-pending",
                           error="Current snapshot verification is pending; retry shortly")
        response.status_code = 503
        response.headers["Retry-After"] = "1"
        response.headers["X-Panel-Verification"] = "pending"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error: Exception):
        request_id = getattr(g, "request_id", "-")
        app.logger.exception(
            "unhandled-error request_id=%s method=%s path=%s error=%s", request_id, request.method, request.path, error
        )
        if isinstance(error, (TimeoutError, ConnectionError)) or (auth_service.psycopg and isinstance(error, auth_service.psycopg.OperationalError)):
            return (jsonify({"status": "unavailable", "error": "Data source temporarily unavailable", "requestId": request_id}), 503, {"Retry-After": "15"})
        return (jsonify({"error": "Internal server error", "requestId": request_id}), 500)
