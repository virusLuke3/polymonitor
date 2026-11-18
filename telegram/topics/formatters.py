from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus

from .catalog import DeliveryMode, delivery_contract
from .generic_formatter import format_generic_snapshot, format_live_generic_snapshot
from .market_linker import MarketLink, market_url_from_row, resolve_market_link
from .models import FormatOutcome, MessageCandidate, source_clock

RELATED_NEWS_GROUP_LIMIT = 2
NEW_MARKET_PLACEHOLDER_TITLE_PREFIXES = (
    "On-chain recovered market ",
    "Trade indexer placeholder market ",
)


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _pct(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    if 0 <= number <= 1:
        number *= 100
    return f"{number:.0f}%"


def _price(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    return f"{number * 100:.0f}c" if 0 <= number <= 1 else f"{number:.2f}"


def _short_hash(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _first_url(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text.startswith("http://") or text.startswith("https://"):
            return text
    return ""


def _clean_tag(value: Any) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or "").strip())
    if not text:
        return ""
    if text[0].isdigit():
        text = f"T{text}"
    return f"#{text[:32]}"


def _hashtags(*values: Any, limit: int = 5) -> str:
    tags: List[str] = []
    seen: set[str] = set()
    for value in values:
        raw_values = value if isinstance(value, list) else [value]
        for raw in raw_values:
            tag = _clean_tag(raw)
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                tags.append(tag)
            if len(tags) >= limit:
                return " ".join(tags)
    return " ".join(tags)


def _polymarket_url(item: Dict[str, Any], *, title: str = "") -> str:
    direct = _first_url(item.get("marketUrl"), item.get("eventUrl"), item.get("url"))
    if direct and "polymarket.com" in direct:
        return direct
    slug = _text(item.get("slug") or item.get("marketSlug") or item.get("eventSlug"))
    if slug:
        if str(item.get("eventSlug") or "").strip() == slug or item.get("eventId"):
            return f"https://polymarket.com/event/{slug}"
        return f"https://polymarket.com/market/{slug}"
    query = _text(item.get("marketTitle") or item.get("question") or item.get("eventTitle")) or title or _text(item.get("title"))
    return f"https://polymarket.com/search?query={quote_plus(query)}" if query else ""


def _market_identity(item: Dict[str, Any], *, title: str = "") -> str:
    return _text(
        item.get("marketId")
        or item.get("eventId")
        or item.get("id")
        or item.get("slug")
        or item.get("marketSlug")
        or item.get("eventSlug")
        or item.get("marketTitle")
        or item.get("question")
        or title
    ).lower()


def _source_link(url: str, label: str = "Open link") -> str:
    return f"{label}: {url}" if url else ""


def _trade_markup(market_link: Optional[MarketLink], *, extra_buttons: List[Dict[str, str]] | None = None) -> Dict[str, Any] | None:
    buttons: List[Dict[str, str]] = []
    if market_link and market_link.url:
        buttons.append({"text": "Trade Polymarket", "url": market_link.url})
    buttons.extend(extra_buttons or [])
    return {"inline_keyboard": [buttons]} if buttons else None


def _compose_post(*, header: str, title: str, lines: Iterable[str] = (), tags: str = "", meme: str = "", url: str = "") -> str:
    parts = [header, title.strip()]
    parts.extend(line.strip() for line in lines if str(line or "").strip())
    if meme:
        parts.append(meme)
    if tags:
        parts.append(tags)
    if url:
        parts.append(url)
    return "\n".join(part for part in parts if part)


def _iter_items(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for item in payload.get("items") or []:
        if isinstance(item, dict):
            yield item


def format_nba_scoreboard(payload: Dict[str, Any]) -> List[MessageCandidate]:
    messages: List[MessageCandidate] = []
    for game in _iter_items(payload):
        game_id = _text(game.get("id") or game.get("eventId") or game.get("name"))
        away = _text(game.get("awayTeam"), "Away")
        home = _text(game.get("homeTeam"), "Home")
        away_score = _text(game.get("awayScore"), "-")
        home_score = _text(game.get("homeScore"), "-")
        status = _text(game.get("status") or game.get("state"), "scheduled")
        tipoff = _text(game.get("tipoff"))
        broadcast = _text(game.get("broadcast"))
        score_line = f"{away} {away_score} @ {home} {home_score}" if away_score != "-" or home_score != "-" else f"{away} @ {home}"
        details = " | ".join(part for part in (status, tipoff, broadcast) if part)
        market_link = resolve_market_link(game, title=f"{away} vs {home}", extra_text=(details,))
        tags = _hashtags("NBA", away, home, status)
        meme = "🏀 Vibe: tipoff radar is awake" if "scheduled" in status.lower() else "🏀 Vibe: scoreboard heat"
        text = _compose_post(
            header="🏀 NBA Scoreboard",
            title=score_line,
            lines=[details],
            tags=tags,
            meme=meme,
            url=_source_link(market_link.url, "Market") if market_link else "",
        )
        dedupe = _short_hash("nba-scoreboard", game_id, away_score, home_score, status)
        priority = "high" if str(game.get("state") or "").lower() in {"post", "final"} or "final" in status.lower() else "normal"
        messages.append(
            MessageCandidate(
                topic="nba",
                dedupe_key=dedupe,
                text=text,
                priority=priority,
                metadata={"panel": "nba-scoreboard", "marketLink": market_link.url if market_link else ""},
                link_preview=bool(market_link),
                reply_markup=_trade_markup(market_link),
            )
        )
    return messages


def format_nba_intel(payload: Dict[str, Any]) -> List[MessageCandidate]:
    messages: List[MessageCandidate] = []
    for item in _iter_items(payload):
        headline = _text(item.get("headline") or item.get("title"))
        if not headline:
            continue
        source = _text(item.get("source"), "NBA intel")
        description = _text(item.get("description"))
        url = _first_url(item.get("url"))
        market_link = resolve_market_link(item, title=headline, extra_text=(description, source, "NBA"))
        tags = _hashtags("NBA", source, "Intel")
        text = _compose_post(
            header="📰 NBA Intel",
            title=headline,
            lines=[source, description[:260] if description else ""],
            tags=tags,
            meme="🏀 Vibe: locker-room signal",
            url="\n".join(part for part in (_source_link(market_link.url, "Market") if market_link else "", _source_link(url, "Source")) if part),
        )
        dedupe = _short_hash("nba-intel", url or item.get("id") or headline.lower())
        messages.append(
            MessageCandidate(
                topic="nba",
                dedupe_key=dedupe,
                text=text,
                priority="normal",
                metadata={"panel": "nba-intel", "marketLink": market_link.url if market_link else ""},
                observed_at=source_clock(item, "publishedAt") or 0,
                link_preview=bool(market_link or url),
                reply_markup=_trade_markup(market_link, extra_buttons=[{"text": "Source", "url": url}] if url else None),
            )
        )

    for lineup in payload.get("lineups") or []:
        if not isinstance(lineup, dict):
            continue
        label = _text(lineup.get("label"))
        status = _text(lineup.get("status"))
        starters = lineup.get("starters") if isinstance(lineup.get("starters"), list) else []
        if not label or not starters:
            continue
        starter_names = ", ".join(_text(player.get("playerName")) for player in starters[:6] if isinstance(player, dict) and _text(player.get("playerName")))
        market_link = resolve_market_link(lineup, title=label, extra_text=(starter_names, "NBA lineup"))
        text = _compose_post(
            header="🧾 NBA Lineup",
            title=label,
            lines=[status, starter_names],
            tags=_hashtags("NBA", "Lineup"),
            meme="👀 Vibe: rotation watch",
            url=_source_link(market_link.url, "Market") if market_link else "",
        )
        dedupe = _short_hash("nba-lineup", lineup.get("gameId"), status, starter_names)
        messages.append(
            MessageCandidate(
                topic="nba",
                dedupe_key=dedupe,
                text=text,
                priority="normal",
                metadata={"panel": "nba-intel", "marketLink": market_link.url if market_link else ""},
                link_preview=bool(market_link),
                reply_markup=_trade_markup(market_link),
            )
        )
    return messages


def format_nba_predictor(payload: Dict[str, Any]) -> List[MessageCandidate]:
    messages: List[MessageCandidate] = []
    for item in _iter_items(payload):
        event_id = _text(item.get("eventId") or item.get("id") or item.get("shortName"))
        away = _text(item.get("awayTeam"), "Away")
        home = _text(item.get("homeTeam"), "Home")
        away_prob = _number(item.get("awayWinProbability"))
        home_prob = _number(item.get("homeWinProbability"))
        quality = _number(item.get("matchupQuality"))
        margin = _number(item.get("projectedMargin"))
        if away_prob is None and home_prob is None and quality is None:
            continue
        line = f"{away} {_pct(away_prob)} | {home} {_pct(home_prob)}"
        extras = []
        if quality is not None:
            extras.append(f"quality {quality:.0f}")
        if margin is not None:
            extras.append(f"margin {margin:+.1f}")
        status = _text(item.get("status") or item.get("state"))
        if status:
            extras.append(status)
        market_link = resolve_market_link(item, title=f"{away} vs {home}", extra_text=(status, "NBA matchup predictor"))
        text = _compose_post(
            header="🔮 NBA Matchup Predictor",
            title=f"{away} @ {home}",
            lines=[line, " | ".join(extras)],
            tags=_hashtags("NBA", away, home, "Predictor"),
            meme="🧠 Vibe: probability board says hello",
            url=_source_link(market_link.url, "Market") if market_link else "",
        )
        dedupe = _short_hash("nba-predictor", event_id, round(away_prob or -1), round(home_prob or -1), status)
        messages.append(
            MessageCandidate(
                topic="nba",
                dedupe_key=dedupe,
                text=text,
                priority="normal",
                metadata={"panel": "espn-matchup-predictor", "marketLink": market_link.url if market_link else ""},
                observed_at=source_clock(item, "lastModified"),
                link_preview=bool(market_link),
                reply_markup=_trade_markup(market_link),
            )
        )
    return messages


def format_esports_intel(payload: Dict[str, Any]) -> List[MessageCandidate]:
    messages = []
    market_types = {
        "moneyline": "全场胜负", "child_moneyline": "单图胜负", "map_handicap": "地图让分", "totals": "总地图数",
    }
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        stamp = source_clock(event, "occurredAt")
        if not stamp or not all(event.get(field) for field in ("id", "title", "action")):
            continue
        phase = str(event["id"]).partition(":")[2].partition(":")[0]
        action = {"started": "开赛", "final": "完赛"}.get(phase, event["action"])
        score = event.get("score")
        result_parts = [action]
        if score:
            result_parts.append(score)
        if phase == "game" and event.get("seriesScore"):
            result_parts.append(f"系列赛 {event['seriesScore']}")
        result = " · ".join(result_parts)
        context = " · ".join(_text(event.get(key)) for key in ("tournament", "format") if event.get(key))
        lines = [result, context]
        if maps := event.get("maps"):
            cs2 = event.get("gameTitle") == "CS2"
            unit = "图" if cs2 else "局"
            games = []
            for game in maps:
                label = f"第{game['number']}{unit}"
                if cs2 and game.get("map"):
                    label += f" {game['map']}"
                games.append(f"{label} {game['score']}")
            lines.append(f"单{unit}比分（按队名顺序） · {' | '.join(games)}")
        market = event.get("polymarket") or {}
        link = market_url_from_row(market)
        if link:
            resolution = market.get("resolution")
            if resolution == "resolved" and market.get("closed"):
                winner = market.get("winner")
                status = f"{winner} 胜，已结算" if winner else "已结算"
            elif resolution in ("proposed", "disputed"):
                status = "结算结果已提议" if resolution == "proposed" else "结算有争议"
            elif market.get("acceptingOrders"):
                status = "接受订单"
            else:
                status = "最终结果待确认"
            lines.append(f"Polymarket 全场胜负 · {status}")
            if kinds := [market_types[k] for k in market.get("types", []) if k in market_types]:
                lines.append(f"盘口 · {'、'.join(kinds)}")
        source_time = datetime.fromtimestamp(stamp, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"GRID · 北京时间 {source_time}")
        messages.append(MessageCandidate(
            topic="intel",
            dedupe_key=f"grid-esports:{event['id']}",
            text=_compose_post(header="🎮 Esports · GRID", title=event["title"], lines=lines, url=link),
            metadata={"panel": "esports-intel"},
            observed_at=stamp,
        ))
    return messages


def format_crypto_fear_greed(index: Dict[str, Any]) -> MessageCandidate | None:
    history = index.get("history") or []
    if index.get("source") != "Alternative.me" or len(history) < 2:
        return None
    latest = history[0]
    stamp = source_clock(latest, "observedAt")
    if stamp is None:
        return None
    day = int(stamp) // 86400
    by_day = {row["observedAt"] // 86400: row for row in history}
    previous = by_day.get(day - 1)
    if previous is None:
        return None
    score, classification = latest["score"], latest["classification"]
    change = score - previous["score"]
    if abs(change) < 5 and classification == previous["classification"]:
        return None

    labels = {
        "Extreme Fear": "极度恐惧", "Fear": "恐惧", "Neutral": "中性",
        "Greed": "贪婪", "Extreme Greed": "极度贪婪",
    }
    signal = labels.get(classification, classification)
    previous_label = labels.get(previous["classification"], previous["classification"])
    lines = [f"{score}/100 · {signal}", f"较昨日 {change:+d} 点（{previous['score']} → {score}）"]
    if classification != previous["classification"]:
        lines.append(f"情绪级别 · {previous_label} → {signal}")
    comparisons = [
        f"{days} 日前 {row['score']}（{score - row['score']:+d} 点）"
        for days in (7, 30) if (row := by_day.get(day - days))
    ]
    if comparisons:
        lines.append(" · ".join(comparisons))
    month = [row for date, row in by_day.items() if day - 29 <= date <= day]
    if len(month) > 1:
        values = [row["score"] for row in month]
        extreme = sum(row["classification"] == "Extreme Fear" for row in month)
        lines.append(f"近 30 日区间 {min(values)}–{max(values)} · 极度恐惧 {extreme}/{len(month)} 个有读数日")
    source_time = datetime.fromtimestamp(stamp, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    lines.append(f"Alternative.me · Bitcoin 情绪指数 · 源时间 {source_time} 北京时间")
    return MessageCandidate(
        topic="alpha", dedupe_key=f"alternative-me:fng:{day}",
        text="\n".join(["📊 加密恐惧与贪婪指数", *lines]),
        metadata={"panel": "crypto-fear-greed"}, observed_at=stamp,
    )


def format_funding_settlements(payload: Dict[str, Any]) -> List[MessageCandidate]:
    messages = []
    for batch in (payload.get("settlementWatch") or {}).get("batches") or []:
        stamp = source_clock(batch, "settledAt")
        if not stamp or not batch.get("id"):
            continue
        assets: dict[str, list[str]] = {}
        for row in sorted(batch.get("rows") or [], key=lambda item: (item["asset"], item["exchange"], item["symbol"])):
            rate = _number(row.get("ratePercent"))
            if rate is not None:
                assets.setdefault(row["asset"], []).append(f"{row['exchange']} {row['symbol']} {rate:+.6f}%")
        if not assets:
            continue
        time_label = datetime.fromtimestamp(batch["dueAt"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"{asset} · {' | '.join(values)}" for asset, values in assets.items()]
        messages.append(MessageCandidate(
            topic="alpha",
            dedupe_key=f"funding-settlement:{batch['id']}",
            text="\n".join(["💰 资金费率已结算", time_label, *lines]),
            metadata={"panel": "crypto-funding-watch"},
            observed_at=stamp,
        ))
    return messages


def format_weather_map(payload: Dict[str, Any], *, summary_only: bool = False) -> List[MessageCandidate]:
    messages: List[MessageCandidate] = []
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    hottest = summary.get("hottestCity") if isinstance(summary.get("hottestCity"), dict) else None
    if hottest:
        city = _text(hottest.get("city"), "Unknown")
        current = _text(hottest.get("currentTemp"), "n/a")
        high = _text(hottest.get("forecastHigh"), "n/a")
        live_count = _text(summary.get("liveMarketCount"), "0")
        dedupe = _short_hash("weather-summary", city, current, high, live_count)
        text = _compose_post(
            header="🌦 Weather Monitor",
            title=f"Hottest mapped city: {city}",
            lines=[f"Current {current} | forecast high {high}", f"Live weather markets: {live_count}"],
            tags=_hashtags("Weather", city, "Heat"),
            meme="🥵 Vibe: thermometer doing cardio",
        )
        messages.append(MessageCandidate(topic="weather", dedupe_key=dedupe, text=text, priority="normal", metadata={"panel": "global-weather-map"}))

    if summary_only:
        return messages
    for item in _iter_items(payload):
        top_bin = item.get("topBin") if isinstance(item.get("topBin"), dict) else {}
        market_url = _first_url(item.get("marketUrl"))
        if not top_bin or not market_url:
            continue
        city = _text(item.get("city"), "Unknown")
        label = _text(top_bin.get("label") or top_bin.get("title") or top_bin.get("raw"))
        market_link = resolve_market_link(item, title=f"{city}: {label}", extra_text=(market_url, "weather"))
        trade_url = market_link.url if market_link else market_url
        quote = _price(top_bin.get("midPriceYes"))
        coverage = _text(item.get("quoteCoverage"))
        temp = _text(item.get("currentTemp"), "n/a")
        dedupe = _short_hash("weather-market", item.get("cityId"), item.get("eventSlug"), label, quote)
        text = _compose_post(
            header="🌦 Weather Market",
            title=f"{city}: {label}",
            lines=[f"YES {quote} | current {temp} | quotes {coverage}"],
            tags=_hashtags("Weather", city, "Polymarket"),
            meme="☁️ Vibe: forecast meets order book",
            url=_source_link(trade_url, "Market"),
        )
        messages.append(
            MessageCandidate(
                topic="weather",
                dedupe_key=dedupe,
                text=text,
                priority="high",
                metadata={"panel": "global-weather-map", "marketLink": trade_url},
                link_preview=True,
                reply_markup=_trade_markup(market_link or (MarketLink(url=market_url, title=label, matched_by="payload") if market_url else None)),
            )
        )
    return messages


def format_weather_news(payload: Dict[str, Any]) -> List[MessageCandidate]:
    messages: List[MessageCandidate] = []
    for article in _iter_items(payload):
        severity = _text(article.get("severity"), "normal").lower()
        if severity not in {"warning", "watch"}:
            continue
        title = _text(article.get("title"))
        if not title:
            continue
        city = _text(article.get("city"))
        source = _text(article.get("source"), "Weather news")
        summary = _text(article.get("summary"))
        url = _first_url(article.get("url"))
        market_link = resolve_market_link(article, title=title, extra_text=(summary, city, source, "weather"))
        tags = _hashtags("Weather", severity, city, article.get("tags") or [], source)
        text = _compose_post(
            header=f"🚨 Weather {severity.title()}",
            title=title,
            lines=[" | ".join(part for part in (city, source) if part), summary[:260] if summary and summary != title else ""],
            tags=tags,
            meme="🌩 Vibe: skies are speaking",
            url="\n".join(part for part in (_source_link(market_link.url, "Market") if market_link else "", _source_link(url, "Source")) if part),
        )
        dedupe = _short_hash("weather-news", url or article.get("id") or title.lower())
        priority = "high" if severity == "warning" else "normal"
        messages.append(
            MessageCandidate(
                topic="weather",
                dedupe_key=dedupe,
                text=text,
                priority=priority,
                metadata={"panel": "weather-news", "marketLink": market_link.url if market_link else ""},
                observed_at=source_clock(article, "publishedAt") or 0,
                link_preview=bool(market_link or url),
                reply_markup=_trade_markup(market_link, extra_buttons=[{"text": "Source", "url": url}] if url else None),
            )
        )
    return messages


def format_latest_content(payload: Dict[str, Any]) -> List[MessageCandidate]:
    messages: List[MessageCandidate] = []
    for item in _iter_items(payload):
        title = _text(item.get("title") or item.get("headline"))
        if not title:
            continue
        source = _text(item.get("source"), "News")
        summary = _text(item.get("summary") or item.get("description"))
        url = _first_url(item.get("url"))
        market_link = resolve_market_link(item, title=title, extra_text=(summary, source, item.get("contentType")))
        text = _compose_post(
            header="💬 News",
            title=title,
            lines=[source, summary[:280] if summary and summary != title else ""],
            tags=_hashtags("News", source, item.get("contentType")),
            meme="🗞 Vibe: fresh tape",
            url="\n".join(part for part in (_source_link(market_link.url, "Market") if market_link else "", _source_link(url, "Source")) if part),
        )
        dedupe = _short_hash("latest-content", url or item.get("id") or title.lower())
        messages.append(
            MessageCandidate(
                topic="news",
                dedupe_key=dedupe,
                text=text,
                metadata={"panel": "latest-content", "marketLink": market_link.url if market_link else ""},
                observed_at=source_clock(item, "publishedAt", "published_at") or 0,
                link_preview=bool(market_link or url),
                reply_markup=_trade_markup(market_link, extra_buttons=[{"text": "Source", "url": url}] if url else None),
            )
        )
    return messages


def format_related_news(payload: Dict[str, Any]) -> List[MessageCandidate]:
    items = list(_iter_items(payload))
    if not items:
        return []
    market_title = _text(payload.get("marketTitle") or payload.get("question"), "Focused market")
    market_id = _text(payload.get("marketId") or payload.get("localMarketId"))
    category = _text(payload.get("marketCategory"))
    market_link = resolve_market_link(payload, title=market_title, extra_text=(category,))
    counts: Dict[str, int] = {}
    for item in items:
        content_type = _text(item.get("contentType"), "news").lower()
        counts[content_type] = counts.get(content_type, 0) + 1
    count_line = " | ".join(
        f"{label} {counts.get(key, 0)}"
        for key, label in (("news", "News"), ("video", "Video"), ("report", "Reports"), ("research", "Research"))
        if counts.get(key, 0)
    )
    grouped: Dict[str, List[str]] = {"news": [], "video": [], "report": [], "research": []}
    first_url = ""
    source_labels: List[str] = []
    for item in items:
        title = _text(item.get("title") or item.get("headline"))
        if not title:
            continue
        source = _text(item.get("source"), "Related intel")
        content_type = _text(item.get("contentType"), "news").lower()
        group_key = content_type if content_type in grouped else "news"
        url = _first_url(item.get("url"))
        if not first_url and url:
            first_url = url
        if source and source not in source_labels:
            source_labels.append(source)
        if len(grouped[group_key]) < RELATED_NEWS_GROUP_LIMIT:
            published = _text(item.get("publishedAt"))
            relation = _text(item.get("relation"))
            detail = " | ".join(part for part in (source, published, relation) if part)
            grouped[group_key].append(f"- {detail} | {title[:140]}")
    section_lines: List[str] = []
    for key, label in (("news", "News"), ("video", "Video"), ("report", "Reports"), ("research", "Research")):
        lines = grouped[key]
        if not lines:
            continue
        section_lines.append(f"{label}:")
        section_lines.extend(lines)
    if not section_lines:
        return []
    text = _compose_post(
        header="Market Intel",
        title=market_title,
        lines=[
            count_line,
            *section_lines,
            f"Source mode: {_text(payload.get('sourceMode'))}" if payload.get("sourceMode") else "",
        ],
        tags=_hashtags("MarketIntel", category, source_labels[:3]),
        url="\n".join(part for part in (_source_link(market_link.url, "Market") if market_link else "", _source_link(first_url, "Top source")) if part),
    )
    version_items = []
    for key in ("news", "video", "report", "research"):
        version_items.extend(grouped[key])
    version = "|".join(version_items)
    dedupe = _short_hash("related-news-summary", market_id, version, len(items), count_line)
    if len(items) == 1:
        item = items[0]
        dedupe = _short_hash("related-news-article", first_url or item.get("id") or item.get("title") or item.get("headline"))
    return [
        MessageCandidate(
            topic="intel",
            dedupe_key=dedupe,
            text=text,
            metadata={"panel": "related-news", "marketId": market_id},
            observed_at=max((source_clock(item, "publishedAt", "published_at") or 0 for item in items), default=0),
            link_preview=bool(market_link or first_url),
            reply_markup=_trade_markup(market_link, extra_buttons=[{"text": "Top source", "url": first_url}] if first_url else None),
        )
    ]


def format_smart_money_signals(payload: Dict[str, Any]) -> List[MessageCandidate]:
    if payload.get("source") != "matched-trades-v2" or payload.get("status") != "ok":
        return []
    messages = []
    for item in _iter_items(payload):
        signal_id = _text(item.get("id"))
        title = _text(item.get("title"), "Polymarket trade")
        outcome = _text(item.get("outcome"), "—")
        side = _text(item.get("side"))
        stamp = source_clock(item, "tradedAt")
        amount, price = (_number(item.get(key)) for key in ("amountUsdc", "averagePrice"))
        if (
            not re.fullmatch(r"[0-9a-f]{64}", signal_id) or side not in ("BUY", "SELL")
            or stamp is None or amount is None or not 0 <= amount < float("inf")
            or price is None or not 0 <= price <= 1
        ):
            continue
        size_text = f"{amount:,.4f}".rstrip("0").rstrip(".")
        price_text = f"{price * 100:.4f}".rstrip("0").rstrip(".")
        traded_at = datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        tags = item.get("tags")
        reasons = " / ".join(tag for tag in tags if isinstance(tag, str)) if isinstance(tags, list) else ""
        slug = _text(item.get("eventSlug"))
        url = f"https://polymarket.com/event/{slug}" if re.fullmatch(r"[a-z0-9-]+", slug) else ""
        trade = f"{side.title()} {outcome} · {size_text} USDC @ {price_text}¢"
        messages.append(MessageCandidate(
            topic="alpha",
            dedupe_key=f"smart-money:{signal_id}",
            text=_compose_post(
                header="🧠 Smart Money · Alpha Signal",
                title=title,
                lines=[trade, traded_at, reasons],
                url=_source_link(url, "Polymarket"),
            ),
            metadata={"panel": "alpha-signal", "market": (title, url, reasons), "line": f"{traded_at} · {trade}"},
            observed_at=stamp,
        ))
    return messages


def format_new_market_signals(payload: Dict[str, Any]) -> List[MessageCandidate]:
    messages: List[MessageCandidate] = []
    for item in _iter_items(payload):
        title = _text(item.get("title") or item.get("question") or item.get("marketTitle") or item.get("eventTitle"))
        if not title or any(title.startswith(prefix) for prefix in NEW_MARKET_PLACEHOLDER_TITLE_PREFIXES):
            continue
        status = _text(item.get("status") or item.get("signal") or item.get("reason"))
        probability = _text(item.get("initialYesProbability"))
        probability_line = f"Initial YES probability: {_pct(probability)}" if probability else ""
        market_link = resolve_market_link(item, title=title, extra_text=(status,))
        url = market_link.url if market_link else _polymarket_url(item, title=title)
        asset_tags = _title_tags(title)
        text = _compose_post(
            header="🆕 New Market Signal",
            title=title,
            lines=[status[:260] if status else "", probability_line, _text(item.get("marketCreatedAt"))],
            tags=_hashtags("NewMarket", "Polymarket", asset_tags),
            meme="🧪 Vibe: fresh market just spawned",
            url=_source_link(url, "Market/Search"),
        )
        dedupe = _short_hash("new-market-signal", _market_identity(item, title=title))
        messages.append(
            MessageCandidate(
                topic="alpha",
                dedupe_key=dedupe,
                text=text,
                priority="normal",
                metadata={"panel": "new-market-signals", "marketLink": url},
                observed_at=source_clock(item, "marketCreatedAt") or 0,
                link_preview=bool(url),
                reply_markup=_trade_markup(market_link or (MarketLink(url=url, title=title, matched_by="fallback") if url else None)),
            )
        )
    return messages


def format_macro_payload(payload: Dict[str, Any], *, panel_label: str, panel_id: str) -> List[MessageCandidate]:
    messages: List[MessageCandidate] = []
    for item in _iter_items(payload):
        title = _text(item.get("title") or item.get("eventTitle") or item.get("name") or item.get("label") or item.get("metric"))
        if not title:
            continue
        status = _text(item.get("status") or item.get("signal") or item.get("summary") or item.get("description"))
        value = _text(item.get("value") or item.get("actual") or item.get("forecast") or item.get("probability"))
        source_url = _first_url(item.get("sourceUrl"))
        market_link = resolve_market_link(item, title=title, extra_text=(status, value, item.get("categoryLabels") or item.get("categoryIds") or []))
        url = market_link.url if market_link else (_polymarket_url(item, title=title) or source_url)
        top_outcomes = item.get("topOutcomes") if isinstance(item.get("topOutcomes"), list) else []
        outcome_line = ""
        if top_outcomes:
            labels = []
            for outcome in top_outcomes[:3]:
                if not isinstance(outcome, dict):
                    continue
                label = _text(outcome.get("label") or outcome.get("title"))
                yes = _price(outcome.get("yesPrice"))
                if label:
                    labels.append(f"{label} YES {yes}")
            outcome_line = " | ".join(labels)
        text = _compose_post(
            header=f"📈 {panel_label}",
            title=title,
            lines=[status[:260] if status else "", f"value: {value}" if value else "", outcome_line],
            tags=_hashtags("Macro", "Polymarket", item.get("categoryLabels") or item.get("categoryIds") or []),
            meme="📊 Vibe: macro board is moving",
            url="\n".join(part for part in (_source_link(url, "Market") if url else "", _source_link(source_url, "Source") if source_url and source_url != url else "") if part),
        )
        dedupe = _short_hash(panel_id, item.get("id") or item.get("eventId") or item.get("slug"), title.lower(), status, value, outcome_line)
        messages.append(
            MessageCandidate(
                topic="macro",
                dedupe_key=dedupe,
                text=text,
                priority="normal",
                metadata={"panel": panel_id, "marketLink": url},
                observed_at=source_clock(item, "newestSourceObservedAt", "sourceObservedAt"),
                link_preview=bool(url or source_url),
                reply_markup=_trade_markup(market_link or (MarketLink(url=url, title=title, matched_by="fallback") if url else None), extra_buttons=[{"text": "Source", "url": source_url}] if source_url and source_url != url else None),
            )
        )
    return messages


def _title_tags(title: str) -> List[str]:
    known = ("BTC", "Bitcoin", "ETH", "Ethereum", "SOL", "Solana", "DOGE", "Dogecoin", "XRP", "Hyperliquid", "NBA", "Fed", "CPI")
    lowered = title.lower()
    return [tag for tag in known if tag.lower() in lowered]


def _format_specialized(panel_id: str, payload: Dict[str, Any], *, live: bool = False) -> List[MessageCandidate]:
    if panel_id == "latest-content":
        return format_latest_content(payload)
    if panel_id == "related-news":
        return format_related_news(payload)
    if panel_id == "alpha-signal":
        return format_smart_money_signals(payload)
    if panel_id == "new-market-signals":
        return format_new_market_signals(payload)
    if panel_id == "polymarket-macro-map":
        return format_macro_payload(payload, panel_label="Macro market map", panel_id=panel_id)
    if panel_id == "cpi-release-command-center":
        return format_macro_payload(payload, panel_label="CPI command center", panel_id=panel_id)
    if panel_id == "nba-scoreboard":
        return format_nba_scoreboard(payload)
    if panel_id == "nba-intel":
        return format_nba_intel(payload)
    if panel_id == "espn-matchup-predictor":
        return format_nba_predictor(payload)
    if panel_id == "esports-intel":
        return format_esports_intel(payload)
    if panel_id == "crypto-funding-watch":
        return format_funding_settlements(payload)
    if panel_id == "global-weather-map":
        return format_weather_map(payload, summary_only=live)
    if panel_id == "weather-news":
        return format_weather_news(payload)
    return []


def format_panel_snapshot_outcome(
    panel_id: str, payload: Dict[str, Any], *, live: bool = False,
) -> FormatOutcome:
    requested_id = str(panel_id or "").strip()
    canonical_id = {
        "related-intel": "related-news",
    }.get(requested_id, requested_id)
    contract = delivery_contract(canonical_id)
    if contract is None:
        return FormatOutcome(
            panel_id=requested_id,
            mode="unsupported",
            reason="panel is not present in the Telegram delivery catalog",
        )
    if not isinstance(payload, dict):
        return FormatOutcome(
            panel_id=canonical_id,
            mode="format-error",
            reason="payload is not an object",
        )
    try:
        if contract.mode is DeliveryMode.SPECIALIZED:
            candidates = _format_specialized(canonical_id, payload, live=live)
        elif contract.mode is DeliveryMode.GENERIC:
            formatter = format_live_generic_snapshot if live else format_generic_snapshot
            candidates = formatter(canonical_id, payload, topic=contract.topic)
        else:
            return FormatOutcome(
                panel_id=canonical_id,
                mode=contract.mode.value,
                reason=contract.reason,
            )
    except Exception as exc:
        return FormatOutcome(
            panel_id=canonical_id,
            mode="format-error",
            reason=f"formatter raised {exc.__class__.__name__}",
        )
    reason = "" if candidates else "formatter produced no candidate for the current payload"
    return FormatOutcome(
        panel_id=canonical_id,
        mode=contract.mode.value,
        candidates=tuple(candidates),
        reason=reason,
    )


def format_panel_snapshot(panel_id: str, payload: Dict[str, Any]) -> List[MessageCandidate]:
    """Compatibility wrapper for existing callers that only consume candidates."""
    return list(format_panel_snapshot_outcome(panel_id, payload).candidates)


def format_all_snapshots_with_stats(
    snapshots: Dict[str, Dict[str, Any]], *, live: bool = False,
) -> tuple[List[MessageCandidate], Dict[str, int]]:
    messages: List[MessageCandidate] = []
    stats = {
        "specialized": 0,
        "generic": 0,
        "empty": 0,
        "aggregate": 0,
        "market_scoped": 0,
        "browser_only": 0,
        "non_pushable": 0,
        "unsupported": 0,
        "format_errors": 0,
    }
    for panel_id, payload in snapshots.items():
        outcome = format_panel_snapshot_outcome(panel_id, payload, live=live)
        messages.extend(outcome.candidates)
        if outcome.mode == DeliveryMode.SPECIALIZED.value:
            stats["specialized"] += 1
        elif outcome.mode == DeliveryMode.GENERIC.value:
            stats["generic"] += 1
        elif outcome.mode == DeliveryMode.AGGREGATE.value:
            stats["aggregate"] += 1
        elif outcome.mode == DeliveryMode.MARKET_SCOPED.value:
            stats["market_scoped"] += 1
        elif outcome.mode == DeliveryMode.BROWSER_ONLY.value:
            stats["browser_only"] += 1
        elif outcome.mode == DeliveryMode.NON_PUSHABLE.value:
            stats["non_pushable"] += 1
        elif outcome.mode == "unsupported":
            stats["unsupported"] += 1
        elif outcome.mode == "format-error":
            stats["format_errors"] += 1
        if not outcome.candidates and outcome.mode in {
            DeliveryMode.SPECIALIZED.value,
            DeliveryMode.GENERIC.value,
        }:
            stats["empty"] += 1
    return messages, stats
