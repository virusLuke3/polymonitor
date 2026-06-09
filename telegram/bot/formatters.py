from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List
from urllib.parse import quote_plus


ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
WORLDCUP_WORKSPACE_URL = "https://www.polymonitor.club/?workspace=worldcup"


def is_address(value: str) -> bool:
    return bool(ADDRESS_RE.match(str(value or "").strip()))


def short_address(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 14:
        return text
    return f"{text[:6]}...{text[-4:]}"


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _money(value: Any) -> str:
    number = _decimal(value)
    if number is None:
        return "n/a"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _pct(value: Any) -> str:
    number = _decimal(value)
    if number is None:
        return "n/a"
    if Decimal("0") <= number <= Decimal("1"):
        number *= Decimal("100")
    return f"{number:.1f}%"


def money(value: Any) -> str:
    return _money(value)


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _truncate(value: Any, limit: int = 120) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _tag(value: Any) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or "").strip())
    if not text:
        return ""
    if text[0].isdigit():
        text = f"T{text}"
    return f"#{text[:32]}"


def _tags(values: Iterable[Any], *, limit: int = 4) -> str:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, list):
            raw_items = value
        else:
            raw_items = [value]
        for raw in raw_items:
            tag = _tag(raw)
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                result.append(tag)
            if len(result) >= limit:
                return " ".join(result)
    return " ".join(result)


def _polymarket_url(item: Dict[str, Any]) -> str:
    for key in ("marketUrl", "eventUrl", "url"):
        value = _text(item.get(key))
        if value.startswith("https://polymarket.com") or value.startswith("http://polymarket.com"):
            return value
    slug = _text(item.get("slug") or item.get("marketSlug") or item.get("eventSlug"))
    if slug:
        return f"https://polymarket.com/event/{slug}"
    title = _text(item.get("title") or item.get("marketTitle") or item.get("question"))
    return f"https://polymarket.com/search?query={quote_plus(title)}" if title else ""


def _parse_time(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _beijing_time(value: Any) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return _text(value, "n/a")
    beijing = parsed.astimezone(timezone(timedelta(hours=8)))
    return beijing.strftime("%Y-%m-%d %H:%M Beijing")


def _items(payload: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    rows = payload.get(key) if isinstance(payload.get(key), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _worldcup_match_label(match: Dict[str, Any]) -> str:
    home = _text(match.get("homeTeam"), "Home")
    away = _text(match.get("awayTeam"), "Away")
    return f"{home} vs {away}"


def _worldcup_match_text(match: Dict[str, Any]) -> str:
    parts = [
        _worldcup_match_label(match),
        _beijing_time(match.get("kickoffUtc")),
        _text(match.get("city")),
        _text(match.get("venue")),
    ]
    return " | ".join(part for part in parts if part)


def _query_terms(query: str) -> List[str]:
    return [part for part in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", str(query or "").lower()) if part]


def _match_score(query: str, item: Dict[str, Any], fields: Iterable[str]) -> int:
    terms = _query_terms(query)
    if not terms:
        return 0
    haystack = " ".join(_text(item.get(field)) for field in fields).lower()
    return sum(1 for term in terms if term in haystack)


def _find_matches(query: str, dashboard: Dict[str, Any], *, limit: int = 6) -> List[Dict[str, Any]]:
    matches = _items(dashboard, "matches")
    if not query.strip():
        return matches[:limit]
    scored = [
        (_match_score(query, match, ("homeTeam", "awayTeam", "city", "venue", "group", "round")), match)
        for match in matches
    ]
    return [match for score, match in sorted(scored, key=lambda row: row[0], reverse=True) if score > 0][:limit]


def _find_weather(query: str, dashboard: Dict[str, Any]) -> List[Dict[str, Any]]:
    weather = _items(dashboard, "weather")
    if not query.strip():
        return weather[:5]
    scored = [(_match_score(query, row, ("cityId", "city", "venue")), row) for row in weather]
    return [row for score, row in sorted(scored, key=lambda row: row[0], reverse=True) if score > 0][:5]


def _weather_rain(row: Dict[str, Any]) -> int:
    current = row.get("current") if isinstance(row.get("current"), dict) else {}
    forecast = row.get("forecast") if isinstance(row.get("forecast"), list) else []
    values = [_decimal(current.get("precipitationProbability")) or Decimal("0")]
    for day in forecast[:3]:
        if isinstance(day, dict):
            values.append(_decimal(day.get("precipitationProbability")) or Decimal("0"))
    return int(max(values or [Decimal("0")]))


def start_text() -> str:
    return "\n".join(
        [
            "PolyMonitorBot",
            "",
            "World Cup:",
            "/worldcup - 世界杯总览",
            "/matches - 最近比赛",
            "/match mexico south africa - 查比赛时间/地点/情报",
            "/team mexico - 查球队新闻和赛程",
            "/venue dallas - 查场馆天气",
            "/news mexico - 查相关新闻",
            "/odds mexico south africa - 查 Polymarket 市场/胜率",
            "",
            "可用命令：",
            "/market bitcoin - 搜索 Polymarket 市场",
            "/wallet 0x... - 查看地址交易画像",
            "/pnl 0x... - 查看地址 PnL 覆盖状态",
            "/signal polymarket - 查看最新 alpha signals",
            "/alert BTC 95000 - 创建价格提醒",
            "",
            f"Workspace: {WORLDCUP_WORKSPACE_URL}",
        ]
    )


def help_text() -> str:
    return "\n".join(
        [
            "PolyMonitorBot Help",
            "",
            "World Cup:",
            "  /worldcup",
            "  /matches",
            "  /match mexico south africa",
            "  /team mexico",
            "  /venue dallas",
            "  /weather dallas",
            "  /news mexico",
            "  /odds mexico south africa",
            "",
            "Market:",
            "  /market nba",
            "  /market bitcoin",
            "",
            "Wallet:",
            "  /wallet 0x123...",
            "  /pnl 0x123...",
            "",
            "Signals:",
            "  /signal polymarket",
            "",
            "Alerts:",
            "  /alert BTC 95000",
            "  /alerts",
            "  /alert_remove 1",
        ]
    )


def format_market_search(query: str, payload: Dict[str, Any]) -> str:
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not raw_items and payload.get("title"):
        raw_items = [payload]
    if not raw_items:
        return f"⚠️ Market\n没有找到：{query}\n试试：/market bitcoin 或 /market nba"
    lines = [f"🔎 Market Search: {query}", ""]
    for index, item in enumerate(raw_items[:5], start=1):
        if not isinstance(item, dict):
            continue
        title = _truncate(item.get("title") or item.get("marketTitle") or item.get("question"), 100)
        price = item.get("latestPrice") or item.get("price") or item.get("probability")
        volume = item.get("volume24h") or item.get("volume")
        trades = item.get("tradeCount24h") or item.get("tradeCount")
        tags = _tags([item.get("tags") or [], item.get("category")])
        url = _polymarket_url(item)
        lines.append(f"{index}. {title}")
        if price not in (None, ""):
            lines.append(f"YES: {_pct(price)}")
        detail_parts = []
        if volume not in (None, ""):
            detail_parts.append(f"Volume 24h: {_money(volume)}")
        if trades not in (None, ""):
            detail_parts.append(f"Trades 24h: {trades}")
        if detail_parts:
            lines.append(" | ".join(detail_parts))
        if tags:
            lines.append(tags)
        if url:
            lines.append(url)
        lines.append("")
    return "\n".join(lines).strip()


def _wallet_labels(summary: Dict[str, Any], daily: List[Dict[str, Any]]) -> List[str]:
    labels: List[str] = []
    trade_count = int(summary.get("tradeCount") or 0)
    active_markets = int(summary.get("activeMarkets") or 0)
    last_trade_at = _parse_time(summary.get("lastTradeAt"))
    first_trade_at = _parse_time(summary.get("firstTradeAt"))
    now = datetime.now(timezone.utc)
    if trade_count >= 100:
        labels.append("高频交易者")
    if active_markets >= 10:
        labels.append("多市场活跃")
    if last_trade_at and last_trade_at >= now - timedelta(days=7):
        labels.append("最近 7 天活跃")
    if trade_count <= 3 or (first_trade_at and first_trade_at >= now - timedelta(days=14)):
        labels.append("新地址")
    recent_trade_count = sum(int(row.get("tradeCount") or 0) for row in daily[-7:] if isinstance(row, dict))
    if recent_trade_count >= 50 and "高频交易者" not in labels:
        labels.append("高频交易者")
    return labels or ["已追踪地址"]


def format_wallet(address: str, summary_payload: Dict[str, Any], trades_payload: Dict[str, Any] | None = None) -> str:
    if summary_payload.get("error") or not summary_payload.get("summary"):
        return "\n".join(
            [
                "⚠️ Wallet",
                "地址服务暂时不可用，或该地址暂无本地统计。",
                f"地址：{short_address(address)}",
                "稍后再试，或先使用 /market 查询市场。",
            ]
        )
    summary = summary_payload.get("summary") if isinstance(summary_payload.get("summary"), dict) else {}
    daily = summary_payload.get("daily") if isinstance(summary_payload.get("daily"), list) else []
    top_markets = summary_payload.get("topMarkets") if isinstance(summary_payload.get("topMarkets"), list) else []
    recent_trades = (trades_payload or {}).get("items") if isinstance((trades_payload or {}).get("items"), list) else []
    lines = [
        "👛 Wallet",
        f"地址：{short_address(summary_payload.get('address') or address)}",
        f"总交易次数：{int(summary.get('tradeCount') or 0):,}",
        f"买入/卖出：{int(summary.get('buyCount') or 0):,} / {int(summary.get('sellCount') or 0):,}",
        f"交易量：{_money(summary.get('volumeNotional'))} USDC",
        f"活跃市场数：{int(summary.get('activeMarkets') or 0):,}",
    ]
    if summary.get("lastTradeAt"):
        lines.append(f"最近交易：{summary.get('lastTradeAt')}")
    if top_markets:
        lines.extend(["", "主要交易市场："])
        for index, market in enumerate(top_markets[:3], start=1):
            title = _truncate(market.get("title") or market.get("slug") or market.get("marketId"), 72)
            lines.append(f"{index}. {title}")
    if recent_trades:
        lines.extend(["", "最近交易："])
        for trade in recent_trades[:3]:
            title = _truncate(trade.get("marketTitle") or trade.get("market_title") or trade.get("marketId"), 56)
            side = _text(trade.get("side"))
            outcome = _text(trade.get("outcome"))
            price = _text(trade.get("price"))
            lines.append(f"- {side} {outcome} @ {price} | {title}")
    labels = _wallet_labels(summary, daily)
    lines.extend(["", "风险标签："])
    lines.extend(f"- {label}" for label in labels)
    return "\n".join(lines)


def format_pnl_coverage(address: str, payload: Dict[str, Any] | None = None) -> str:
    payload = payload or {}
    if payload.get("status") == "ok" and payload.get("tradingPnl") is not None:
        return "\n".join(
            [
                "📊 Wallet PnL",
                f"地址：{short_address(address)}",
                f"Trading PnL：{_money(payload.get('tradingPnl'))} USDC",
                f"Realized cash：{_money(payload.get('realizedCash'))} USDC",
                f"Unrealized value：{_money(payload.get('unrealizedValue'))} USDC",
            ]
        )
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    return "\n".join(
        [
            "📊 PnL",
            f"地址：{short_address(address)}",
            "",
            "当前状态：PnL 正在接入 cashflow 层",
            "暂不输出完整 PnL，避免用不完整数据误导。",
            "",
            "Data coverage:",
            f"- trade cashflows: {coverage.get('tradeCashflows', False)}",
            f"- non-trade cashflows: {coverage.get('nonTradeCashflows', False)}",
            f"- position snapshot: {coverage.get('positionSnapshot', False)}",
        ]
    )


def format_signals(topic: str, payload: Dict[str, Any]) -> str:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items:
        return f"⚠️ Signal\n暂时没有找到信号：{topic}"
    lines = [f"🐳 Alpha Signals: {topic}", ""]
    for index, item in enumerate(items[:5], start=1):
        if not isinstance(item, dict):
            continue
        title = _truncate(item.get("title") or item.get("marketTitle") or item.get("summary"), 100)
        summary = _truncate(item.get("summary") or item.get("signal") or item.get("reason"), 150)
        tags = _tags([item.get("kind"), item.get("severity"), item.get("contributors") or [], item.get("sourceTag")])
        lines.append(f"{index}. {title}")
        if summary and summary != title:
            lines.append(summary)
        if tags:
            lines.append(tags)
        url = _polymarket_url(item)
        if url:
            lines.append(url)
        lines.append("")
    return "\n".join(lines).strip()


def format_worldcup_overview(dashboard: Dict[str, Any], intel: Dict[str, Any] | None = None) -> str:
    intel = intel or {}
    tournament = dashboard.get("tournament") if isinstance(dashboard.get("tournament"), dict) else {}
    matches = _items(dashboard, "matches")
    news = _items(intel, "news") or _items(dashboard, "news")
    signals = _items(intel, "signals")
    weather = _items(intel, "weather") or _items(dashboard, "weather")
    provider_states = intel.get("providerStates") if isinstance(intel.get("providerStates"), dict) else {}
    live_providers = sum(1 for value in provider_states.values() if str(value).lower() == "ok")
    lines = [
        "⚽ worldcup",
        _text(tournament.get("name"), "FIFA World Cup 2026"),
        f"Providers {live_providers} | Matches {len(matches)} | Signals {len(signals)} | News {len(news)} | Weather {len(weather)}",
        "",
        "Next matches:",
    ]
    for match in matches[:5]:
        lines.append(f"- {_worldcup_match_text(match)}")
    lines.extend(["", f"Workspace: {WORLDCUP_WORKSPACE_URL}"])
    return "\n".join(lines).strip()


def format_worldcup_matches(dashboard: Dict[str, Any], query: str = "") -> str:
    matches = _find_matches(query, dashboard, limit=8)
    if not matches:
        return f"⚠️ worldcup matches\n没有找到比赛：{query}\n试试：/matches 或 /match mexico"
    header = f"⚽ worldcup matches: {query}" if query.strip() else "⚽ worldcup next matches"
    lines = [header, ""]
    for index, match in enumerate(matches, start=1):
        lines.append(f"{index}. {_worldcup_match_label(match)}")
        lines.append(f"   Time: {_beijing_time(match.get('kickoffUtc'))}")
        lines.append(f"   Venue: {_text(match.get('venue'))}, {_text(match.get('city'))}")
        group = _text(match.get("group") or match.get("round") or match.get("stage"))
        if group:
            lines.append(f"   Stage: {group}")
    lines.extend(["", f"Workspace: {WORLDCUP_WORKSPACE_URL}"])
    return "\n".join(lines).strip()


def format_worldcup_match(query: str, dashboard: Dict[str, Any], intel: Dict[str, Any] | None = None) -> str:
    matches = _find_matches(query, dashboard, limit=1)
    if not matches:
        return f"⚠️ worldcup match\n没有找到比赛：{query}\n试试：/match mexico south africa"
    match = matches[0]
    intel = intel or {}
    label = _worldcup_match_label(match)
    terms = " ".join((_text(match.get("homeTeam")), _text(match.get("awayTeam")), query))
    signals = [
        item for item in _items(intel, "signals")
        if _match_score(terms, item, ("title", "summary", "source", "category")) > 0
    ][:4]
    news = [
        item for item in (_items(intel, "news") or _items(dashboard, "news"))
        if _match_score(terms, item, ("title", "summary", "source")) > 0
    ][:3]
    weather_rows = [row for row in _items(dashboard, "weather") if _text(row.get("cityId")) == _text(match.get("cityId"))]
    lines = [
        f"⚽ {label}",
        f"Kickoff: {_beijing_time(match.get('kickoffUtc'))}",
        f"Venue: {_text(match.get('venue'))}, {_text(match.get('city'))}",
        f"Group/Round: {_text(match.get('group') or match.get('round') or match.get('stage'), 'n/a')}",
    ]
    if weather_rows:
        current = weather_rows[0].get("current") if isinstance(weather_rows[0].get("current"), dict) else {}
        lines.append(f"Weather: {_text(current.get('condition'), 'n/a')} | {_text(current.get('tempC'), 'n/a')}C | rain {_weather_rain(weather_rows[0])}%")
    if signals:
        lines.extend(["", "Signals:"])
        for item in signals:
            lines.append(f"- {_truncate(item.get('title'), 120)}")
    if news:
        lines.extend(["", "News:"])
        for item in news:
            lines.append(f"- {_text(item.get('source'), 'news')} | {_truncate(item.get('title'), 120)}")
    lines.extend(["", f"Odds: /odds {query}", f"Workspace: {WORLDCUP_WORKSPACE_URL}"])
    return "\n".join(lines).strip()


def format_worldcup_team(query: str, dashboard: Dict[str, Any], intel: Dict[str, Any] | None = None) -> str:
    matches = _find_matches(query, dashboard, limit=5)
    intel = intel or {}
    news = [
        item for item in (_items(intel, "news") or _items(dashboard, "news"))
        if _match_score(query, item, ("title", "summary", "source")) > 0
    ][:4]
    signals = [
        item for item in _items(intel, "signals")
        if _match_score(query, item, ("title", "summary", "source", "category")) > 0
    ][:4]
    if not matches and not news and not signals:
        return f"⚠️ worldcup team\n没有找到球队相关信息：{query}\n试试：/team mexico"
    lines = [f"⚽ team: {query}", ""]
    if matches:
        lines.append("Matches:")
        for match in matches:
            lines.append(f"- {_worldcup_match_text(match)}")
    if signals:
        lines.extend(["", "Signals:"])
        for item in signals:
            lines.append(f"- {_truncate(item.get('title'), 120)}")
    if news:
        lines.extend(["", "News:"])
        for item in news:
            lines.append(f"- {_text(item.get('source'), 'news')} | {_truncate(item.get('title'), 120)}")
    lines.extend(["", f"Workspace: {WORLDCUP_WORKSPACE_URL}"])
    return "\n".join(lines).strip()


def format_worldcup_venue(query: str, dashboard: Dict[str, Any]) -> str:
    rows = _find_weather(query, dashboard)
    if not rows:
        return f"⚠️ worldcup venue\n没有找到场馆/城市：{query}\n试试：/venue dallas 或 /weather atlanta"
    lines = [f"⚽ venue/weather: {query or 'top venues'}", ""]
    for row in rows[:5]:
        current = row.get("current") if isinstance(row.get("current"), dict) else {}
        city = _text(row.get("cityId"), "venue")
        lines.append(f"- {city}: {_text(current.get('condition'), 'n/a')} | {_text(current.get('tempC'), 'n/a')}C | wind {_text(current.get('windKph'), 'n/a')} kph | rain {_weather_rain(row)}%")
    lines.extend(["", f"Workspace: {WORLDCUP_WORKSPACE_URL}"])
    return "\n".join(lines).strip()


def format_worldcup_news(query: str, intel: Dict[str, Any], dashboard: Dict[str, Any] | None = None) -> str:
    rows = _items(intel, "news") or _items(dashboard or {}, "news")
    if query.strip():
        rows = [row for row in rows if _match_score(query, row, ("title", "summary", "source")) > 0]
    if not rows:
        return f"⚠️ worldcup news\n没有找到相关新闻：{query or 'latest'}"
    lines = [f"⚽ worldcup news: {query or 'latest'}", ""]
    for index, item in enumerate(rows[:5], start=1):
        lines.append(f"{index}. {_text(item.get('source'), 'news')} | {_truncate(item.get('title'), 130)}")
        summary = _truncate(item.get("summary"), 160)
        if summary:
            lines.append(summary)
        url = _text(item.get("url"))
        if url.startswith("http"):
            lines.append(url)
        lines.append("")
    return "\n".join(lines).strip()


def format_worldcup_odds(query: str, dashboard: Dict[str, Any], market_payload: Dict[str, Any]) -> str:
    matches = _find_matches(query, dashboard, limit=1)
    odds = _items(dashboard, "odds")
    relevant_odds = [row for row in odds if _match_score(query, row, ("title", "marketTitle", "homeTeam", "awayTeam")) > 0][:3]
    lines = [f"⚽ worldcup odds: {query}", ""]
    if matches:
        lines.append(_worldcup_match_text(matches[0]))
        lines.append("")
    if relevant_odds:
        lines.append("Matched odds:")
        for item in relevant_odds:
            lines.append(f"- {_truncate(item.get('title') or item.get('marketTitle'), 120)}")
        lines.append("")
    else:
        lines.append("当前 World Cup dashboard 暂未直接匹配到该场 Polymarket 胜率。")
        lines.append("")
    markets = market_payload.get("items") if isinstance(market_payload.get("items"), list) else []
    if markets:
        lines.append("Polymarket search:")
        for index, item in enumerate(markets[:3], start=1):
            title = _truncate(item.get("title") or item.get("marketTitle") or item.get("question"), 120)
            price = item.get("latestPrice") or item.get("price") or item.get("probability")
            url = _polymarket_url(item)
            lines.append(f"{index}. {title}")
            if price not in (None, ""):
                lines.append(f"   YES: {_pct(price)}")
            if url:
                lines.append(f"   {url}")
    else:
        lines.append("Polymarket search: no local market match yet.")
    lines.extend(["", f"Workspace: {WORLDCUP_WORKSPACE_URL}"])
    return "\n".join(lines).strip()


def crypto_price_map(payload: Dict[str, Any]) -> Dict[str, float]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    prices: Dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label") or item.get("id") or item.get("symbol")).upper()
        symbol = _text(item.get("symbol")).upper().replace("-USD", "")
        price = _decimal(item.get("price"))
        if price is None:
            continue
        for key in (label, symbol):
            if key:
                prices[key] = float(price)
    return prices


def format_alert_created(alert: Dict[str, Any]) -> str:
    direction_text = "高于或等于" if alert.get("direction") == "above" else "低于或等于"
    current = alert.get("createdPrice")
    current_line = f"当前价格：{_money(current)}" if current not in (None, "") else "当前价格：暂不可用"
    return "\n".join(
        [
            "🔔 Alert Created",
            f"ID：{alert.get('id')}",
            f"标的：{alert.get('symbol')}",
            f"条件：价格{direction_text} {_money(alert.get('threshold'))}",
            current_line,
            "",
            "查看：/alerts",
            f"删除：/alert_remove {alert.get('id')}",
        ]
    )


def format_alerts(alerts: list[Dict[str, Any]]) -> str:
    if not alerts:
        return "🔔 Alerts\n当前没有活跃提醒。\n创建示例：/alert BTC 95000"
    lines = ["🔔 Active Alerts", ""]
    for alert in alerts[:20]:
        direction_text = ">=" if alert.get("direction") == "above" else "<="
        lines.append(f"{alert.get('id')}. {alert.get('symbol')} {direction_text} {_money(alert.get('threshold'))}")
    lines.extend(["", "删除：/alert_remove <id>"])
    return "\n".join(lines)


def format_alert_removed(alert_id: int, removed: bool) -> str:
    if removed:
        return f"🔕 Alert Removed\n已删除提醒：{alert_id}"
    return f"⚠️ Alert\n没有找到可删除的提醒：{alert_id}"


def format_alert_triggered(alert: Dict[str, Any], price: float) -> str:
    direction_text = "突破" if alert.get("direction") == "above" else "跌破"
    return "\n".join(
        [
            "🚨 Alert Triggered",
            f"{alert.get('symbol')} 已{direction_text} {_money(alert.get('threshold'))}",
            f"当前价格：{_money(price)}",
            f"Alert ID：{alert.get('id')}",
        ]
    )
