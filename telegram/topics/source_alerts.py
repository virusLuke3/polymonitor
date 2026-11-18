"""Select Telegram updates from upstream clocks and meaningful changes."""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from .formatters import format_crypto_fear_greed, format_esports_intel
from .models import MessageCandidate, source_clock
from .nba_scoreboard import NBA, format_nba_game_update
from .oil_alerts import OIL_STATE, plan_oil_alerts


ESPORTS = "esports-intel"
ORDER_FLOW = "crypto-order-flow"
ORACLE = "crypto-oracle-reference"
COMMODITIES = "commodity-equity-transmission"
WEATHER = "global-weather-map"
FEAR_GREED = "crypto-fear-greed"

# Seconds: maximum source age and minimum interval between alerts for the same instrument.
SOURCE_LIMITS = {
    ESPORTS: (5 * 60, 0),
    ORDER_FLOW: (90, 30 * 60),
    ORACLE: (45, 30 * 60),
    COMMODITIES: (20 * 60, 60 * 60),
    WEATHER: (75 * 60, 2 * 60 * 60),
    FEAR_GREED: (6 * 60 * 60, 0),
    NBA: (5 * 60, 0),
}
STATE_SUFFIX = ":source-alerts-v1"
COMMODITY_FUTURES = {"gasoline", "copper", "aluminum", "natgas", "ttf"}
ALERT_DISPLAY = {
    ORDER_FLOW: ("Crypto spot flow alert", "intel", "Bybit trades"),
    ORACLE: ("Crypto oracle price alert", "intel", "Polymarket / Chainlink TWAP"),
    COMMODITIES: ("Commodity price alert", "macro", "Yahoo Finance quote"),
    WEATHER: ("Weather observation alert", "weather", "METAR"),
}


@dataclass(frozen=True)
class Reading:
    entity: str
    at: float
    value: float
    text: str
    direction: int = 0
    reset: bool = True
    sample_start: float | None = None


def _number(value):
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _direction(value, threshold):
    return 1 if value >= threshold else -1 if value <= -threshold else 0


def _readings(panel, payload):
    if panel == ORDER_FLOW:
        for asset, row in (payload.get("assets") or {}).items():
            flow = row.get("flow") or {}
            start, stamp = source_clock(flow, "from"), source_clock(flow, "to")
            net, buy, sell = (_number(flow.get(key)) for key in ("net", "buy", "sell"))
            if not start or not stamp or start > stamp or None in (net, buy, sell) or flow.get("count") != 60:
                continue
            gross = buy + sell
            if gross <= 0 or min(buy, sell) < 0:
                continue
            imbalance = abs(net) / gross
            yield Reading(
                asset, stamp, net,
                f"Bybit spot · {asset}\nNet {net:+,.0f} USD across 60 trades · {imbalance:.0%} net imbalance",
                _direction(net, 250_000) if imbalance >= .70 else 0,
                abs(net) <= 150_000 or imbalance <= .50, start,
            )
    elif panel == ORACLE:
        for asset, row in (payload.get("references") or {}).items():
            latest = row.get("latest") or {}
            stamp = source_clock(latest, "event_at_ms")
            price = _number(latest.get("value"))
            if row.get("status") != "ok" or not stamp or price is None or price <= 0:
                continue
            points = ((source_clock(point, "t"), _number(point.get("v"))) for point in row.get("history") or ())
            prior = min(
                ((abs(at - (stamp - 300)), value) for at, value in points
                 if at and value is not None and value > 0 and 285 <= stamp - at <= 315),
                default=None,
            )
            if prior is None:
                continue
            change = (price / prior[1] - 1) * 100
            yield Reading(
                asset, stamp, change, f"{asset} reference price {price:,.8g} USD · {change:+.2f}% in about 5 min",
                _direction(change, 1), abs(change) <= .65,
            )
    elif panel == COMMODITIES:
        for row in payload.get("items") or ():
            if row.get("id") not in COMMODITY_FUTURES or row.get("instrumentType") != "FUTURE":
                continue
            symbol = row.get("symbol")
            stamp = source_clock(row, "quoteAt")
            change, price = _number(row.get("changePercent")), _number(row.get("price"))
            if not symbol or not stamp or change is None or price is None or price <= 0:
                continue
            if row.get("acquisitionState") != "ok" or row.get("changeBasis") != "previous-close":
                continue
            yield Reading(
                symbol, stamp, change,
                f"{row.get('label') or symbol} ({symbol}) · {price:g}\n"
                f"{change:+.2f}% vs previous close",
                _direction(change, 2), abs(change) <= 1.5,
            )
    elif panel == WEATHER:
        for row in payload.get("items") or ():
            stamp = source_clock(row, "observationUpdatedAt")
            temp, city, unit = _number(row.get("metarTemp")), row.get("cityId"), row.get("unit")
            if row.get("observationState") == "ok" and stamp and temp is not None and city and unit in ("C", "F"):
                yield Reading(f"{city}:{unit}", stamp, temp, f"{row.get('city') or city} · {temp:g}°{unit}")


def _clock(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def plan_source_alerts(snapshots, heads, *, now, prime):
    candidates, updates, baselined = [], {}, []
    if oil := (snapshots.get(COMMODITIES) or {}).get("oil"):
        events, observation, primed = plan_oil_alerts(
            oil, heads.get(OIL_STATE), now=now, prime=prime, max_age=SOURCE_LIMITS[COMMODITIES][0],
        )
        candidates.extend(events)
        updates[OIL_STATE] = observation
        if primed:
            baselined.append(OIL_STATE)
    for panel, (max_age, cooldown) in SOURCE_LIMITS.items():
        if panel not in snapshots:
            continue
        payload = snapshots[panel]
        state_key = panel + STATE_SUFFIX
        saved = heads.get(state_key)
        first = prime or saved is None
        after = now if first else saved["after"]
        readings = {} if first else dict(saved["readings"])
        if first:
            baselined.append(panel)

        if panel == NBA:
            readings = {game: old for game, old in readings.items() if now - old["at"] <= 86400}
            for game, detail in (payload.get("gameDetails") or {}).items():
                old = readings.get(game, {})
                try:
                    event = format_nba_game_update(detail, after=after, now=now, max_age=max_age, previous=old)
                except (KeyError, TypeError, ValueError):
                    continue
                if event:
                    candidates.append(event)
                    readings[game] = {"at": event.observed_at, "keys": [*old.get("keys", ()), event.metadata["milestone"]]}
        elif panel == ESPORTS:
            readings = {series: old for series, old in readings.items() if now - old["at"] <= 86400}
            events = sorted(format_esports_intel(payload), key=lambda event: event.observed_at, reverse=True)
            for event in events:
                series = event.dedupe_key.split(":")[1]
                stamp = event.observed_at
                old = readings.get(series, {})
                if not after < stamp <= now or stamp <= old.get("at", 0) or event.dedupe_key == old.get("event"):
                    continue
                readings[series] = {"at": stamp, "event": event.dedupe_key}
                if now - stamp <= max_age:
                    candidates.append(event)
        elif panel == FEAR_GREED:
            index = (payload.get("summary") or {}).get("cryptoIndex") or {}
            history = index.get("history") or []
            stamp = source_clock(history[0], "observedAt") if history else None
            prior_at = readings.get("alternativeMe", {}).get("at", 0)
            if (payload.get("sources", {}).get("alternativeMe") == "ok" and stamp and stamp <= now
                    and int(stamp) // 86400 > int(prior_at) // 86400):
                readings["alternativeMe"] = {"at": stamp}
                if after < stamp and now - stamp <= max_age and (alert := format_crypto_fear_greed(index)):
                    candidates.append(alert)
        else:
            for row in _readings(panel, payload):
                old = readings.get(row.entity)
                if not 0 <= now - row.at <= max_age or old and row.at <= old["at"]:
                    continue
                if old and row.sample_start is not None and row.sample_start <= old["at"]:
                    continue
                alert_at = old.get("alertAt", 0) if old else 0
                direction = row.direction if row.reset or row.direction or not old else old["direction"]
                text = row.text
                triggered = bool(old and row.direction and row.direction != old["direction"])
                if panel == WEATHER and old:
                    unit = row.entity[-1]
                    delta = row.value - old["value"]
                    triggered = row.at - old["at"] <= 90 * 60 and abs(delta) >= (5 if unit == "C" else 9)
                    text += f" · {delta:+g}°{unit} since previous METAR observation"
                if triggered and row.at > after and row.at - alert_at >= cooldown:
                    label, topic, source = ALERT_DISPLAY[panel]
                    candidates.append(MessageCandidate(
                        topic=topic, dedupe_key=f"source-alert:{panel}:{row.entity}:{int(row.at * 1000)}",
                        text=f"📡 {label}\n{text}\n{source} · {_clock(row.at)}",
                        metadata={"panel": panel}, observed_at=row.at,
                    ))
                    alert_at = row.at
                readings[row.entity] = {"at": row.at, "value": row.value, "direction": direction, "alertAt": alert_at}
        updates[state_key] = {"after": after, "readings": readings}
    return candidates, updates, baselined
