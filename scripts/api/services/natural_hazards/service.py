from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping

from api.context import (
    resolve_optional_service_callable,
    resolve_service_value,
)

from .contracts import SCHEMA_VERSION, SourceFetchResult
from .dedupe import latest_revision
from .providers import eonet, firms, nws, usgs
from .snapshots import cached_source_result, fetch_with_snapshot, stale_source_result
from .source_health import unavailable_source


DEFAULT_EVENT_LIMIT = 1200
PROVIDER_DEADLINE_SECONDS = 35


@dataclass(frozen=True)
class NaturalHazardDependencies:
    http_json_get: Callable[..., Any]
    http_text_get: Callable[..., str] | None
    snapshot_store: Any
    logger: Any
    usgs_url: str
    eonet_url: str
    nws_url: str
    firms_map_key: str
    firms_base_url: str
    firms_source: str

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> "NaturalHazardDependencies":
        getter = resolve_optional_service_callable(context, "http_json_get")
        if getter is None:
            raise RuntimeError("natural hazards require http_json_get")
        settings = resolve_service_value(context, "SETTINGS")
        app = resolve_service_value(context, "app")
        return cls(
            http_json_get=getter,
            http_text_get=resolve_optional_service_callable(context, "http_text_get"),
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
            firms_map_key=str(os.environ.get("POLYDATA_FIRMS_MAP_KEY") or "").strip(),
            firms_base_url=str(
                getattr(settings, "natural_hazards_firms_base_url", None)
                or firms.DEFAULT_BASE_URL
            ),
            firms_source=str(
                getattr(settings, "natural_hazards_firms_source", None)
                or firms.DEFAULT_SOURCE
            ),
        )


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fetch_provider_results(
    *,
    dependencies: NaturalHazardDependencies,
    source_specs: Mapping[str, tuple[int, Callable[[], Dict[str, Any]]]],
    deadline_seconds: float = PROVIDER_DEADLINE_SECONDS,
) -> dict[str, SourceFetchResult]:
    results: dict[str, SourceFetchResult] = {}
    executor = ThreadPoolExecutor(max_workers=len(source_specs), thread_name_prefix="natural-hazard")
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
    done, pending = wait(futures, timeout=max(0.01, float(deadline_seconds)))
    for future in done:
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
    for future in pending:
        key = futures[future]
        future.cancel()
        error_code = f"{key}-provider-deadline-exceeded"
        stale = stale_source_result(dependencies.snapshot_store, key, error_code)
        results[key] = stale or {
            **unavailable_source(key, error_code),
            "status": "error",
            "events": [],
        }
    executor.shutdown(wait=False, cancel_futures=True)
    return results


def get_natural_hazards_snapshot(
    context: Mapping[str, Any],
    *,
    limit: int = DEFAULT_EVENT_LIMIT,
    allow_provider_fetch: bool = True,
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
    if dependencies.firms_map_key and dependencies.http_text_get is not None:
        source_specs["firms"] = (
            900,
            lambda: firms.fetch(
                dependencies.http_text_get,
                map_key=dependencies.firms_map_key,
                base_url=dependencies.firms_base_url,
                source=dependencies.firms_source,
                limit=min(firms.MAX_AGGREGATES, bounded_limit),
            ),
        )
    if allow_provider_fetch:
        results = _fetch_provider_results(
            dependencies=dependencies,
            source_specs=source_specs,
        )
    else:
        results = {}
        for key in source_specs:
            cached = cached_source_result(dependencies.snapshot_store, key)
            results[key] = cached or {
                **unavailable_source(key, f"{key}-snapshot-unavailable"),
                "status": "error",
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
    if "firms" not in results:
        error_code = "configuration-required" if not dependencies.firms_map_key else "http-text-get-unavailable"
        sources.append(unavailable_source("firms", error_code))
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
