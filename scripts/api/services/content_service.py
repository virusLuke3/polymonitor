from __future__ import annotations

from api.context import RuntimeResources, runtime_resources

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Dict

from api.context import (
    resolve_optional_service_callable,
    resolve_service_callable,
)


_RELATED_CONTENT_CACHE_TTL_SECONDS = 120
_RELATED_CONTENT_SNAPSHOT_TTL_SECONDS = 300


@dataclass(frozen=True)
class RelatedContentDependencies:
    resources: RuntimeResources
    get_related_content_by_market_id: Callable[..., Any]
    query_one: Callable[..., Any]
    get_snapshot_payload: Callable[..., Any] | None
    table_exists: Callable[..., Any] | None

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> RelatedContentDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            resources=runtime_resources(context),
            get_related_content_by_market_id=resolve_service_callable(
                    context,
                    "get_related_content_by_market_id",
                ),
            query_one=resolve_service_callable(context, "query_one"),
            get_snapshot_payload=resolve_optional_service_callable(
                context,
                "get_snapshot_payload",
            ),
            table_exists=resolve_optional_service_callable(
                context,
                "table_exists",
            ),
        )


@dataclass(frozen=True)
class LatestContentDependencies:
    get_latest_content_snapshot: Callable[..., Any]

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> LatestContentDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            get_latest_content_snapshot=resolve_service_callable(context, "get_latest_content_snapshot"),
        )


def _related_content_version(
    dependencies: RelatedContentDependencies,
    market_id: int,
) -> Dict[str, Any]:
    try:
        if dependencies.table_exists is None or not (
            dependencies.table_exists("content_items")
            and dependencies.table_exists("content_links")
        ):
            return {"links": 0, "linkCreatedAt": "", "itemUpdatedAt": ""}
        row = dependencies.query_one(
            """
            SELECT
                COUNT(*) AS links,
                MAX(cl.created_at) AS link_created_at,
                MAX(ci.updated_at) AS item_updated_at
            FROM content_links cl
            JOIN content_items ci ON ci.id = cl.content_id
            WHERE cl.market_id = ?
            """,
            (market_id,),
        ) or {}
        return {
            "links": int(row.get("links") or 0),
            "linkCreatedAt": str(row.get("link_created_at") or ""),
            "itemUpdatedAt": str(row.get("item_updated_at") or ""),
        }
    except Exception:
        return {"links": 0, "linkCreatedAt": "", "itemUpdatedAt": ""}


def _get_related_content_payload_uncached(
    dependencies: RelatedContentDependencies,
    market_id: int,
    limit: int = 8,
) -> Dict[str, Any]:
    return dependencies.get_related_content_by_market_id(market_id, limit=limit)


def _get_related_content_payload_local_cached(
    dependencies: RelatedContentDependencies,
    market_id: int,
    limit: int = 8,
) -> Dict[str, Any]:
    cache_key = (int(market_id), int(limit))
    now = time.time()
    with dependencies.resources.content_lock:
        cached = dependencies.resources.related_content.get(cache_key)
        if cached and now - cached[0] < _RELATED_CONTENT_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["sourceMode"] = f"{payload.get('sourceMode') or 'database'}:cache"
            return payload
    payload = dependencies.get_related_content_by_market_id(market_id, limit=limit)
    with dependencies.resources.content_lock:
        dependencies.resources.related_content[cache_key] = (now, payload)
        if len(dependencies.resources.related_content) > 256:
            oldest_key = min(dependencies.resources.related_content, key=lambda key: dependencies.resources.related_content[key][0])
            dependencies.resources.related_content.pop(oldest_key, None)
    return payload


def get_related_content_payload(
    ctx: Mapping[str, Any],
    market_id: int,
    limit: int = 8,
    days: int = 7,
    market: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    dependencies = RelatedContentDependencies.from_context(ctx)
    options = {"limit": limit, "days": days}
    if market is not None:
        options["market"] = market
    return dependencies.get_related_content_by_market_id(market_id, **options)


def get_latest_content_payload(
    ctx: Mapping[str, Any],
    limit: int = 8,
    days: int = 7,
) -> Dict[str, Any]:
    dependencies = LatestContentDependencies.from_context(ctx)
    return dependencies.get_latest_content_snapshot(limit=limit, days=days)
