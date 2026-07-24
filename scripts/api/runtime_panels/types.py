from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, cast

from api.context import resolve_route_callable, resolve_route_value


PanelPayload = Dict[str, Any]
MarketSymbol = tuple[str, str, str]


@dataclass(frozen=True)
class RuntimePanelContext(Mapping[str, Any]):
    """Typed dependencies for runtime panels during the module migration."""

    source: Mapping[str, Any] = field(repr=False)
    commodity_symbols: Sequence[MarketSymbol]
    crypto_symbols: Sequence[MarketSymbol]
    get_market_group_snapshot: Callable[..., PanelPayload]
    get_breaking_event_radar_snapshot: Callable[..., PanelPayload]
    get_market_tv_wire_snapshot: Callable[..., PanelPayload]
    get_market_youtube_channels_snapshot: Callable[..., PanelPayload]
    get_global_weather_map_snapshot: Callable[..., PanelPayload]
    get_weather_news_snapshot: Callable[..., PanelPayload]

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> RuntimePanelContext:
        return cls(
            source=context,
            commodity_symbols=cast(
                Sequence[MarketSymbol],
                resolve_route_value(context, "COMMODITY_SYMBOLS", ()),
            ),
            crypto_symbols=cast(
                Sequence[MarketSymbol],
                resolve_route_value(context, "CRYPTO_SYMBOLS", ()),
            ),
            get_market_group_snapshot=cast(
                Callable[..., PanelPayload],
                resolve_route_callable(context, "get_market_group_snapshot"),
            ),
            get_breaking_event_radar_snapshot=cast(
                Callable[..., PanelPayload],
                resolve_route_callable(context, "get_breaking_event_radar_snapshot"),
            ),
            get_market_tv_wire_snapshot=cast(
                Callable[..., PanelPayload],
                resolve_route_callable(context, "get_market_tv_wire_snapshot"),
            ),
            get_market_youtube_channels_snapshot=cast(
                Callable[..., PanelPayload],
                resolve_route_callable(context, "get_market_youtube_channels_snapshot"),
            ),
            get_global_weather_map_snapshot=cast(
                Callable[..., PanelPayload],
                resolve_route_callable(context, "get_global_weather_map_snapshot"),
            ),
            get_weather_news_snapshot=cast(
                Callable[..., PanelPayload],
                resolve_route_callable(context, "get_weather_news_snapshot"),
            ),
        )

    def __getitem__(self, name: str) -> Any:
        return self.source[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.source)

    def __len__(self) -> int:
        return len(self.source)


@dataclass(frozen=True)
class RuntimePanelModule:
    panel_id: str
    route: str
    default_limit: int | None
    min_limit: int | None
    max_limit: int | None
    get_snapshot: Callable[..., PanelPayload]
    default_enabled: bool = True

    def clamp_limit(self, raw_value: Any = None) -> int | None:
        if self.default_limit is None:
            return None
        try:
            value = int(raw_value if raw_value is not None else self.default_limit)
        except (TypeError, ValueError):
            value = self.default_limit
        if self.min_limit is not None:
            value = max(self.min_limit, value)
        if self.max_limit is not None:
            value = min(self.max_limit, value)
        return value
