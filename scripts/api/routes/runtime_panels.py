from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from api.runtime_panels import RUNTIME_PANEL_MODULES, get_panel_by_id
from api.services import hls_proxy_service


def _publish_runtime_panel(panel_id: str, payload: dict) -> None:
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

    for panel in RUNTIME_PANEL_MODULES:
        endpoint = f"api_runtime_panel_{panel.panel_id.replace('-', '_')}"

        def _handler(panel=panel):
            limit = panel.clamp_limit(request.args.get("limit"))
            payload = _get_panel_snapshot(panel, helpers, limit)
            _publish_runtime_panel(panel.panel_id, payload)
            return jsonify(payload)

        bp.add_url_rule(panel.route, endpoint, _handler, methods=["GET"])

    return bp
