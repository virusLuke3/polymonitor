from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, g, jsonify, make_response, request


@dataclass(frozen=True)
class AuthRouteDependencies:
    auth_enabled: Callable[[], bool]
    authenticate_request: Callable[..., Any]
    change_password: Callable[..., None]
    create_api_key: Callable[..., dict[str, Any]]
    list_api_keys: Callable[..., list[dict[str, Any]]]
    list_audit_log: Callable[..., list[dict[str, Any]]]
    login: Callable[..., Any]
    logout: Callable[..., None]
    request_metadata: Callable[[Any], dict[str, Any]]
    revoke_api_key: Callable[..., None]
    session_cookie_name: Callable[[], str]
    session_snapshot: Callable[[Any], Any]
    session_ttl_seconds: Callable[[], int]
    cookie_secure: Callable[[], bool]
    allowed_scopes: tuple[str, ...]


def _payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def _metadata(dependencies: AuthRouteDependencies) -> dict[str, Any]:
    metadata = dependencies.request_metadata(request)
    metadata["request_id"] = getattr(g, "request_id", "")
    return metadata


def _set_session_cookie(response: Any, dependencies: AuthRouteDependencies, token: str) -> None:
    response.set_cookie(
        dependencies.session_cookie_name(),
        token,
        max_age=dependencies.session_ttl_seconds(),
        secure=dependencies.cookie_secure(),
        httponly=True,
        samesite="Lax",
        path="/",
    )


def _clear_session_cookie(response: Any, dependencies: AuthRouteDependencies) -> None:
    response.delete_cookie(
        dependencies.session_cookie_name(),
        secure=dependencies.cookie_secure(),
        httponly=True,
        samesite="Lax",
        path="/",
    )


def create_auth_blueprint(dependencies: AuthRouteDependencies) -> Blueprint:
    bp = Blueprint("auth_routes", __name__)

    @bp.route("/auth/session", methods=["GET"])
    def auth_session():
        principal, csrf_token = dependencies.session_snapshot(request)
        response = {
            "enabled": dependencies.auth_enabled(),
            "authenticated": principal is not None,
            "user": principal.public_user() if principal else None,
            "csrfToken": csrf_token,
            "allowedScopes": list(dependencies.allowed_scopes),
        }
        return jsonify(response)

    @bp.route("/auth/login", methods=["POST"])
    def auth_login():
        data = _payload()
        principal, raw_token, csrf_token = dependencies.login(
            data.get("username"),
            data.get("password"),
            _metadata(dependencies),
        )
        response = make_response(
            jsonify(
                {
                    "authenticated": True,
                    "user": principal.public_user(),
                    "csrfToken": csrf_token,
                }
            )
        )
        _set_session_cookie(response, dependencies, raw_token)
        return response

    @bp.route("/auth/logout", methods=["POST"])
    def auth_logout():
        principal = dependencies.authenticate_request(request, require_csrf=True)
        dependencies.logout(request, principal, _metadata(dependencies))
        response = make_response(jsonify({"status": "ok"}))
        _clear_session_cookie(response, dependencies)
        return response

    @bp.route("/auth/password", methods=["POST"])
    def auth_password():
        principal = dependencies.authenticate_request(request, require_csrf=True)
        data = _payload()
        dependencies.change_password(
            principal,
            data.get("currentPassword"),
            data.get("newPassword"),
            _metadata(dependencies),
        )
        return jsonify({"status": "ok", "forcePasswordChange": False})

    @bp.route("/auth/api-keys", methods=["GET"])
    def auth_api_keys():
        principal = dependencies.authenticate_request(request, required_role="admin")
        return jsonify(
            {"items": dependencies.list_api_keys(principal), "allowedScopes": list(dependencies.allowed_scopes)}
        )

    @bp.route("/auth/api-keys", methods=["POST"])
    def auth_create_api_key():
        principal = dependencies.authenticate_request(request, required_role="admin", require_csrf=True)
        data = _payload()
        scopes = data.get("scopes")
        item = dependencies.create_api_key(
            principal,
            name=data.get("name"),
            scopes=scopes if isinstance(scopes, list) else [],
            rate_limit=data.get("rateLimitPerMinute"),
            daily_quota=data.get("dailyQuota"),
            metadata=_metadata(dependencies),
        )
        return jsonify({"item": item}), 201

    @bp.route("/auth/api-keys/<string:key_id>", methods=["DELETE"])
    def auth_revoke_api_key(key_id: str):
        principal = dependencies.authenticate_request(request, required_role="admin", require_csrf=True)
        dependencies.revoke_api_key(principal, key_id, _metadata(dependencies))
        return jsonify({"status": "ok"})

    @bp.route("/auth/audit", methods=["GET"])
    def auth_audit():
        dependencies.authenticate_request(request, required_role="admin")
        return jsonify({"items": dependencies.list_audit_log(request.args.get("limit", 100, type=int) or 100)})

    return bp
