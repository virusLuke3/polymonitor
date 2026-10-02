from __future__ import annotations

import os
from concurrent.futures import wait
from time import monotonic
from threading import Lock
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping

from api.context import RuntimeResources, runtime_resources, resolve_optional_service_callable

from .contracts import SCHEMA_VERSION, SourceFetchResult
from .dedupe import latest_revision
from .providers import eccc, swic, eonet, firms, gdacs, nhc, ncei, nws, usgs, usgs_volcano_cap
from .snapshots import cached_source_result, fetch_with_snapshot, stale_source_result
from .source_health import unavailable_source


DEFAULT_EVENT_LIMIT = 1200
# Keep the aggregate deadline below the browser's 25 second map request budget.
# Individual provider workers may finish later, but stale snapshots are returned
# immediately once this bounded deadline expires.
PROVIDER_DEADLINE_SECONDS = 12
# The compact browser feed uses a 10 second request timeout. Return retained
# source data (or an isolated source error) before the client aborts; the
# provider worker may still finish and populate the shared snapshot.
SOURCE_PROVIDER_DEADLINE_SECONDS = 6.5


@dataclass(frozen=True)
class NaturalHazardDependencies:
    resources: RuntimeResources
    http_json_get: Callable[..., Any]
    http_text_get: Callable[..., str] | None
    http_bytes_get: Callable[..., bytes] | None
    snapshot_store: Any
    logger: Any
    usgs_url: str
    eonet_url: str
    gdacs_url: str
    nws_url: str
    firms_map_key: str
    firms_base_url: str
    firms_source: str

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> "NaturalHazardDependencies":
        if isinstance(context, cls):
            return context
        getter = resolve_optional_service_callable(context, "http_json_get")
        if getter is None:
            raise RuntimeError("natural hazards require http_json_get")
        settings = context.get("SETTINGS")
        app = context.get("app")
        return cls(
            resources=runtime_resources(context),
            http_json_get=getter,
            http_text_get=resolve_optional_service_callable(context, "http_text_get"),
            http_bytes_get=resolve_optional_service_callable(context, "http_bytes_get"),
            snapshot_store=context.get("SNAPSHOT_STORE"),
            logger=getattr(app, "logger", None),
            usgs_url=str(
                getattr(settings, "natural_hazards_usgs_url", None)
                or usgs.DEFAULT_URL
            ),
            eonet_url=str(
                getattr(settings, "natural_hazards_eonet_url", None)
                or eonet.DEFAULT_URL
            ),
            gdacs_url=str(
                getattr(settings, "natural_hazards_gdacs_url", None)
                or gdacs.DEFAULT_URL
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
    resources = dependencies.resources
    with resources.hazard_lock_guard:
        for key in source_specs:
            resources.hazard_locks.setdefault(key, Lock())
    futures = {}
    # Never hold the scheduler lock during external cache I/O.
    cached_results = {key: cached_source_result(dependencies.snapshot_store, key) for key in source_specs}
    with resources.hazard_lock_guard:
        for key, (ttl, fetcher) in source_specs.items():
            cached = cached_results[key]
            if cached is not None:
                results[key] = cached
                if cached["status"] in {"ok", "partial"}:
                    continue
            future = resources.hazard_pending.get(key)
            if future is None or future.done():
                future = resources.submit(resources.hazard_executor, fetch_with_snapshot,
                    source_lock=resources.hazard_locks[key], key=key,
                    snapshot_store=dependencies.snapshot_store, fetcher=fetcher, ttl_seconds=ttl)
                resources.hazard_pending[key] = future
            if cached is None:
                futures[future] = key
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
        # This shared future remains owned by the source, not a timed-out caller.
        # Another worker (or this future at the deadline boundary) may have
        # published a successful snapshot while wait() returned. Use that
        # verified fresh result before declaring the source degraded.
        cached = cached_source_result(dependencies.snapshot_store, key)
        if cached is not None and cached["status"] in {"ok", "partial"}:
            results[key] = cached
            continue
        error_code = f"{key}-provider-deadline-exceeded"
        stale = stale_source_result(dependencies.snapshot_store, key, error_code)
        results[key] = stale or {
            **unavailable_source(key, error_code),
            "status": "error",
            "events": [],
        }
    if "nws" in results:
        results["nws"]["events"] = nws.enrich_cached_events(results["nws"].get("events", []), dependencies.resources,
            snapshot_store=dependencies.snapshot_store, http_json_get=dependencies.http_json_get)
    return results


def _source_specs(
    dependencies: NaturalHazardDependencies,
    bounded_limit: int,
) -> dict[str, tuple[int, Callable[[], Dict[str, Any]]]]:
    # Snapshot identity is source-wide: never cache a small caller limit as the catalog.
    bounded_limit = DEFAULT_EVENT_LIMIT
    def fetch_nws():
        # Start the deadline when this worker actually runs, not while a caller
        # builds the source catalog or waits for an executor slot.
        previous = stale_source_result(dependencies.snapshot_store, "nws", "nws-previous-snapshot")
        return nws.fetch(dependencies.http_json_get, resources=dependencies.resources,
            url=dependencies.nws_url, limit=min(700, bounded_limit),
            previous_events=(previous or {}).get("events", []),
            snapshot_store=dependencies.snapshot_store,
            deadline=monotonic() + nws.PROVIDER_FETCH_BUDGET_SECONDS)
    specs: dict[str, tuple[int, Callable[[], Dict[str, Any]]]] = {
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
        "gdacs": (
            300,
            lambda: gdacs.fetch(
                dependencies.http_json_get,
                url=dependencies.gdacs_url,
                limit=min(160, bounded_limit),
            ),
        ),
        "nws": (60, fetch_nws),
        "eccc": (120, lambda: eccc.fetch(dependencies.http_json_get)),
        "swic": (120, lambda: swic.fetch(dependencies.http_json_get)),
        "nhc": (
            120,
            lambda: nhc.fetch(
                dependencies.http_json_get,
                http_bytes_get=dependencies.http_bytes_get,
                resources=dependencies.resources,
                limit=min(40, bounded_limit),
            ),
        ),
        "usgs-volcano-cap": (
            300,
            lambda: usgs_volcano_cap.fetch(
                dependencies.http_json_get,
                limit=min(80, bounded_limit),
            ),
        ),
        "climate-anomaly": (
            6 * 60 * 60,
            lambda: ncei.fetch(
                dependencies.http_json_get,
                limit=min(ncei.MAX_EVENTS, bounded_limit),
            ),
        ),
    }
    if dependencies.http_text_get is not None:
        specs["firms"] = (
            900,
            lambda: firms.fetch(
                dependencies.http_text_get,
                map_key=dependencies.firms_map_key,
                base_url=dependencies.firms_base_url,
                source=dependencies.firms_source,
                limit=min(firms.MAX_AGGREGATES, bounded_limit),
                snapshot_store=dependencies.snapshot_store,
                resources=dependencies.resources,
            ),
        )
    return specs


def get_natural_hazard_source_result(
    context: Mapping[str, Any],
    *,
    source: str,
    limit: int = DEFAULT_EVENT_LIMIT,
    allow_provider_fetch: bool = True,
) -> SourceFetchResult:
    """Load exactly one provider so slow sources never head-of-line block peers."""

    key = str(source or "").strip().lower()
    if key not in {"usgs", "usgs-volcano-cap", "eonet", "gdacs", "nws", "eccc", "swic", "nhc", "firms", "climate-anomaly"}:
        raise ValueError("unsupported-natural-hazard-source")
    dependencies = NaturalHazardDependencies.from_context(context)
    bounded_limit = max(1, min(DEFAULT_EVENT_LIMIT, int(limit)))
    spec = _source_specs(dependencies, bounded_limit).get(key)
    if spec is None:
        error_code = "http-text-get-unavailable" if key == "firms" else f"{key}-source-unavailable"
        return {
            **unavailable_source(key, error_code),
            "status": "error",
            "events": [],
        }
    if not allow_provider_fetch:
        result = cached_source_result(dependencies.snapshot_store, key) or {
            **unavailable_source(key, f"{key}-snapshot-unavailable"),
            "status": "error",
            "events": [],
        }
        if key == "nws":
            result["events"] = nws.enrich_cached_events(result["events"], dependencies.resources, snapshot_store=dependencies.snapshot_store)
        return result
    return _fetch_provider_results(
        dependencies=dependencies,
        source_specs={key: spec},
        deadline_seconds=SOURCE_PROVIDER_DEADLINE_SECONDS,
    )[key]


def get_natural_hazards_snapshot(
    context: Mapping[str, Any],
    *,
    limit: int = DEFAULT_EVENT_LIMIT,
    allow_provider_fetch: bool = True,
) -> Dict[str, Any]:
    dependencies = NaturalHazardDependencies.from_context(context)
    bounded_limit = max(1, min(DEFAULT_EVENT_LIMIT, int(limit)))
    source_specs = _source_specs(dependencies, bounded_limit)
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
        if "nws" in results:
            results["nws"]["events"] = nws.enrich_cached_events(results["nws"]["events"], dependencies.resources)

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
        error_code = "http-text-get-unavailable"
        sources.append(unavailable_source("firms", error_code))
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
