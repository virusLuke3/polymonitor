from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus

from telegram.topics.market_linker import MarketLink, resolve_market_link


ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


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
    event_slug = _text(item.get("eventSlug"))
    slug = _text(item.get("slug") or item.get("marketSlug") or item.get("eventSlug"))
    if event_slug and slug and event_slug != slug:
        return f"https://polymarket.com/event/{event_slug}/{slug}"
    if slug:
        return f"https://polymarket.com/event/{slug}"
    title = _text(item.get("title") or item.get("marketTitle") or item.get("question"))
    return f"https://polymarket.com/search?query={quote_plus(title)}" if title else ""


def _resolved_market_link(
    item: Dict[str, Any],
    *,
    title: str = "",
    extra_text: Iterable[Any] = (),
) -> Optional[MarketLink]:
    link = resolve_market_link(item, title=title, extra_text=extra_text)
    if link is not None:
        return link
    url = _polymarket_url(item)
    fallback_title = _text(title or item.get("title") or item.get("marketTitle") or item.get("question") or item.get("eventTitle"))
    if url and fallback_title:
        return MarketLink(url=url, title=fallback_title, matched_by="payload", score=1.0)
    return None


def _trade_links_from_items(items: Iterable[Dict[str, Any]], *, limit: int = 2) -> List[tuple[str, str]]:
    links: List[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        link = _resolved_market_link(
            item,
            title=_text(item.get("title") or item.get("marketTitle") or item.get("question") or item.get("eventTitle")),
            extra_text=(item.get("summary"), item.get("source"), item.get("category")),
        )
        if link is None or not link.url or link.url in seen:
            continue
        seen.add(link.url)
        label = "Trade Polymarket" if not links else "More Markets"
        links.append((label, link.url))
        if len(links) >= limit:
            break
    return links


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


def start_text() -> str:
    return "\n".join(
        [
            "PolyMonitorBot",
            "",
            "可用命令：",
            "/market bitcoin - 搜索 Polymarket 市场",
            "/wallet 0x... - 查看地址交易画像",
            "/pnl 0x... - 查看地址 PnL 覆盖状态",
            "/alert BTC 95000 - 创建价格提醒",
            "",
            "Workspace: https://www.polymonitor.club",
        ]
    )


def help_text() -> str:
    return "\n".join(
        [
            "PolyMonitorBot Help",
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
        link = _resolved_market_link(item, title=title, extra_text=(query, item.get("eventTitle"), item.get("category")))
        url = link.url if link else ""
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


def market_search_action_links(payload: Dict[str, Any]) -> List[tuple[str, str]]:
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not raw_items and payload.get("title"):
        raw_items = [payload]
    return _trade_links_from_items([item for item in raw_items if isinstance(item, dict)], limit=2)


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
