from __future__ import annotations

import os

from flask import Blueprint, Response, jsonify, request

from api.runtime_panels import RUNTIME_PANEL_MODULES, get_panel_by_id
from api.services import hls_proxy_service, youtube_embed_service, youtube_live_probe_service

try:
    import requests as requests_module
except Exception:  # pragma: no cover
    requests_module = None


def _publish_runtime_panel(panel_id: str, payload: dict) -> None:
    if request.headers.get("X-PolyData-Telegram-Publisher") == "1":
        return
    try:
        from telegram.topics.runtime_bridge import publish_panel_snapshot
    except Exception:
        return
    try:
        publish_panel_snapshot(panel_id, payload)
    except Exception:
        return


def _get_panel_snapshot(panel, helpers: dict, limit: int | None):
    kwargs = {}
    if limit is not None:
        kwargs["limit"] = limit
    if panel.panel_id in {"market-tv-wire", "market-youtube-channels"}:
        category = request.args.get("category")
        if category:
            kwargs["category"] = category
    return panel.get_snapshot(helpers, **kwargs)


def create_runtime_panels_blueprint(helpers: dict) -> Blueprint:
    bp = Blueprint("runtime_panel_routes", __name__)

    def _youtube_relay_token() -> str:
        return str(
            os.environ.get("POLYDATA_YOUTUBE_LIVE_RELAY_TOKEN")
            or os.environ.get("RELAY_SHARED_SECRET")
            or ""
        ).strip()

    def _youtube_relay_auth_header() -> str:
        return str(
            os.environ.get("POLYDATA_YOUTUBE_LIVE_RELAY_AUTH_HEADER")
            or os.environ.get("RELAY_AUTH_HEADER")
            or "x-polymonitor-relay-key"
        ).strip() or "x-polymonitor-relay-key"

    def _is_authorized_youtube_relay_request() -> bool:
        expected = _youtube_relay_token()
        if not expected:
            return False
        supplied = request.headers.get(_youtube_relay_auth_header()) or ""
        authorization = request.headers.get("Authorization") or ""
        return supplied == expected or authorization == f"Bearer {expected}"

    @bp.route("/runtime/content/hls-proxy", methods=["GET"])
    def api_runtime_hls_proxy():
        target_url = request.args.get("url") or ""
        try:
            data, content_type, status = hls_proxy_service.fetch_hls_resource(target_url)
        except hls_proxy_service.HlsProxyError as exc:
            return jsonify({"status": "error", "error": str(exc)}), exc.status_code
        except Exception as exc:
            helpers["app"].logger.warning("runtime hls proxy failed url=%s error=%s", target_url[:160], exc)
            return jsonify({"status": "error", "error": "upstream HLS fetch failed"}), 502
        response = Response(data, status=status, content_type=content_type)
        response.headers["Cache-Control"] = hls_proxy_service.cache_control_for(content_type)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @bp.route("/runtime/content/youtube-embed", methods=["GET"])
    def api_runtime_youtube_embed():
        video_id = request.args.get("videoId") or ""
        try:
            origin = request.host_url.rstrip("/")
            html = youtube_embed_service.build_youtube_embed_html(
                video_id=video_id,
                request_origin=origin,
                parent_origin=request.args.get("parentOrigin") or "",
                autoplay=request.args.get("autoplay"),
                mute=request.args.get("mute"),
                quality=request.args.get("vq"),
            )
        except ValueError as exc:
            return Response(str(exc), status=400, content_type="text/plain; charset=utf-8")
        return Response(html, status=200, headers=youtube_embed_service.youtube_embed_headers())

    @bp.route("/runtime/content/youtube-live", methods=["GET"])
    def api_runtime_youtube_live_relay():
        if not _is_authorized_youtube_relay_request():
            return jsonify({"error": "Unauthorized"}), 401
        channel = request.args.get("channel") or ""
        video_id = request.args.get("videoId") or ""
        if not channel and not video_id:
            return jsonify({"error": "Missing channel or videoId parameter"}), 400
        if requests_module is None:
            return jsonify({"error": "requests unavailable"}), 503
        ctx = {
            "requests": requests_module,
            "youtube_live_relay_base_url": "",
        }
        payload = youtube_live_probe_service._fetch_live_stream_info(ctx, channel=channel, video_id=video_id)
        response = jsonify(payload)
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=120"
        return response

    @bp.route("/runtime/panels", methods=["GET"])
    def api_runtime_panels_batch():
        raw_ids = request.args.get("ids") or ""
        panel_ids = [
            panel_id.strip()
            for panel_id in raw_ids.split(",")
            if panel_id.strip()
        ]
        if not panel_ids:
            panel_ids = [panel.panel_id for panel in RUNTIME_PANEL_MODULES]

        payloads = {}
        errors = {}
        for panel_id in dict.fromkeys(panel_ids):
            panel = get_panel_by_id(panel_id)
            if panel is None:
                errors[panel_id] = "unknown-panel"
                continue
            raw_limit = request.args.get(f"limit.{panel_id}") or request.args.get("limit")
            limit = panel.clamp_limit(raw_limit)
            try:
                payload = _get_panel_snapshot(panel, helpers, limit)
                payloads[panel.panel_id] = payload
                _publish_runtime_panel(panel.panel_id, payload)
            except Exception as exc:
                helpers["app"].logger.exception("runtime-panels batch failed panel_id=%s", panel_id)
                errors[panel_id] = exc.__class__.__name__

        status = "ok" if not errors else ("partial" if payloads else "error")
        return jsonify(
            {
                "generatedAt": helpers["utc_now_iso"](),
                "status": status,
                "panels": payloads,
                "errors": errors,
            }
        )

    @bp.route("/runtime/panels/<panel_id>", methods=["GET"])
    def api_runtime_panel_by_id(panel_id: str):
        panel = get_panel_by_id(panel_id)
        if panel is None:
            return jsonify({"error": "unknown-panel", "panelId": panel_id}), 404
        limit = panel.clamp_limit(request.args.get("limit"))
        payload = _get_panel_snapshot(panel, helpers, limit)
        _publish_runtime_panel(panel.panel_id, payload)
        return jsonify(payload)

    for panel in RUNTIME_PANEL_MODULES:
        endpoint = f"api_runtime_panel_{panel.panel_id.replace('-', '_')}"

        def _handler(panel=panel):
            limit = panel.clamp_limit(request.args.get("limit"))
            payload = _get_panel_snapshot(panel, helpers, limit)
            _publish_runtime_panel(panel.panel_id, payload)
            return jsonify(payload)

        bp.add_url_rule(panel.route, endpoint, _handler, methods=["GET"])

    return bp
