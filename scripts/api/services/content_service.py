from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Dict

from api.context import resolve_service_callable


@dataclass(frozen=True)
class RelatedContentDependencies:
    get_related_content_by_market_id: Callable[..., Any]

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> RelatedContentDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            get_related_content_by_market_id=resolve_service_callable(
                context, "get_related_content_by_market_id",
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
