"""Natural-hazard aggregation for the World Event Map."""

from .service import DEFAULT_EVENT_LIMIT, get_natural_hazards_snapshot
from .market_linker import (
    DEFAULT_LIMIT as DEFAULT_RELATED_MARKET_LIMIT,
    related_weather_markets_snapshot,
)

__all__ = [
    "DEFAULT_EVENT_LIMIT",
    "DEFAULT_RELATED_MARKET_LIMIT",
    "get_natural_hazards_snapshot",
    "related_weather_markets_snapshot",
]
