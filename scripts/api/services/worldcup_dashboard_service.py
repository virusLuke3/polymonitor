from __future__ import annotations

from typing import Any, Dict

from api.services.worldcup.builder import build_worldcup_dashboard_payload
from api.services.worldcup.dashboard import get_worldcup_dashboard_snapshot as _get_worldcup_dashboard_snapshot
from api.services.worldcup.payload import (
    fallback_worldcup_dashboard_payload,
    has_generated_fallback_artifacts,
    normalize_payload,
)
from api.services.worldcup.schedule import OPENFOOTBALL_2026_URL, WORLD_CUP_CITIES

WORLDCUP_DASHBOARD_NAMESPACE = "snapshot:sports:worldcup-dashboard"
WORLDCUP_DASHBOARD_CACHE_KEY = "dashboard-v1"
DEFAULT_TTL_SECONDS = 900

# Backward-compatible aliases for watcher/API callers that imported old private helpers.
_normalize_payload = normalize_payload
_has_generated_fallback_artifacts = has_generated_fallback_artifacts
_fallback_worldcup_dashboard_payload = fallback_worldcup_dashboard_payload


def get_worldcup_dashboard_snapshot(ctx: Dict[str, Any]) -> Dict[str, Any]:
    return _get_worldcup_dashboard_snapshot(
        ctx,
        namespace=WORLDCUP_DASHBOARD_NAMESPACE,
        cache_key=WORLDCUP_DASHBOARD_CACHE_KEY,
        default_ttl_seconds=DEFAULT_TTL_SECONDS,
        build_payload=build_worldcup_dashboard_payload,
        normalize_payload=normalize_payload,
        has_generated_fallback_artifacts=has_generated_fallback_artifacts,
        fallback_payload=fallback_worldcup_dashboard_payload,
    )
