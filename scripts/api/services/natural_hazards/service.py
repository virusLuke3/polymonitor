from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping

from api.context import (
    resolve_optional_service_callable,
    resolve_service_value,
)

from .contracts import SCHEMA_VERSION, SourceFetchResult
from .dedupe import latest_revision
from .providers import eonet, nws, usgs
from .snapshots import fetch_with_snapshot
from .source_health import unavailable_source


DEFAULT_EVENT_LIMIT = 1200


@dataclass(frozen=True)
class NaturalHazardDependencies:
    http_json_get: Callable[..., Any]
    snapshot_store: Any
    logger: Any
    usgs_url: str
    eonet_url: str
    nws_url: str

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> "NaturalHazardDependencies":
        getter = resolve_optional_service_callable(context, "http_json_get")
        if getter is None:
            raise RuntimeError("natural hazards require http_json_get")
        settings = resolve_service_value(context, "SETTINGS")
        app = resolve_service_value(context, "app")
        return cls(
            http_json_get=getter,
            snapshot_store=resolve_service_value(context, "SNAPSHOT_STORE"),
            logger=getattr(app, "logger", None),
            usgs_url=str(
                getattr(settings, "natural_hazards_usgs_url", None)
                or usgs.DEFAULT_URL
            ),
            eonet_url=str(
                getattr(settings, "natural_hazards_eonet_url", None)
                or eonet.DEFAULT_URL
            ),
            nws_url=str(
                getattr(settings, "natural_hazards_nws_url", None)
                or nws.DEFAULT_URL
            ),
        )


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_natural_hazards_snapshot(
    context: Mapping[str, Any],
    *,
    limit: int = DEFAULT_EVENT_LIMIT,
) -> Dict[str, Any]:
    dependencies = NaturalHazardDependencies.from_context(context)
    bounded_limit = max(1, min(DEFAULT_EVENT_LIMIT, int(limit)))
    source_specs = {
        "usgs": (
            60,
            lambda: usgs.fetch(
                dependencies.http_json_get,
                url=dependencies.usgs_url,
                limit=min(650, bounded_limit),
            ),
        ),
        "eonet": (
            300,
            lambda: eonet.fetch(
                dependencies.http_json_get,
                url=dependencies.eonet_url,
                limit=min(350, bounded_limit),
            ),
        ),
        "nws": (
            60,
            lambda: nws.fetch(
                dependencies.http_json_get,
                url=dependencies.nws_url,
                limit=min(700, bounded_limit),
            ),
        ),
    }
    results: dict[str, SourceFetchResult] = {}
    with ThreadPoolExecutor(max_workers=len(source_specs), thread_name_prefix="natural-hazard") as executor:
        futures = {
            executor.submit(
                fetch_with_snapshot,
                key=key,
                snapshot_store=dependencies.snapshot_store,
                fetcher=fetcher,
                ttl_seconds=ttl,
            ): key
            for key, (ttl, fetcher) in source_specs.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as exc:  # defensive boundary around provider isolation
                if dependencies.logger is not None:
                    dependencies.logger.exception("natural-hazard provider failed key=%s", key)
                results[key] = {
                    **unavailable_source(key, f"{key}-{exc.__class__.__name__}"),
                    "events": [],
                }

    events = latest_revision(
        event
        for key in source_specs
        for event in results.get(key, {}).get("events", [])
        if not bool((event.get("revision") or {}).get("cancelled"))
    )
    events.sort(
        key=lambda event: str(event.get("updatedAt") or event.get("occurredAt") or ""),
        reverse=True,
    )
    sources = [
        {key: value for key, value in result.items() if key != "events"}
        for result in (results[key] for key in source_specs)
    ]
    if not str(os.environ.get("POLYDATA_FIRMS_MAP_KEY") or "").strip():
        sources.append(unavailable_source("firms", "configuration-required"))
    sources.append(unavailable_source("climate-anomaly", "baseline-pipeline-not-configured"))
    failed_sources = [source for source in sources if source["status"] != "ok"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _generated_at(),
        "events": events[:bounded_limit],
        "sources": sources,
        "isPartial": bool(failed_sources),
        "errors": [
            {"source": source["key"], "code": source.get("errorCode")}
            for source in failed_sources
        ],
        "counts": {
            "events": min(len(events), bounded_limit),
            "byHazardKind": {
                hazard_kind: sum(1 for event in events[:bounded_limit] if event.get("hazardKind") == hazard_kind)
                for hazard_kind in sorted({str(event.get("hazardKind") or "") for event in events if event.get("hazardKind")})
            },
        },
    }
