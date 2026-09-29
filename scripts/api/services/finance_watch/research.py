from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from api.services.finance_watch.common import (
    FinanceWatchContext,
    _compact_source,
    _dependencies,
    _fetch_yahoo_snapshot,
    _format_pct,
    _format_price,
    _http_text_get,
    _news_url,
    _payload,
    _safe_float,
    _setting,
    _strip_html,
)

BROKER_RESEARCH_SYMBOLS = (
    ("NVDA", "Nvidia", "AI"),
    ("AMD", "AMD", "AI"),
    ("MSFT", "Microsoft", "AI"),
    ("AAPL", "Apple", "MEGA"),
    ("AMZN", "Amazon", "MEGA"),
    ("GOOGL", "Alphabet", "MEGA"),
    ("META", "Meta", "MEGA"),
    ("TSLA", "Tesla", "EV"),
    ("COIN", "Coinbase", "CRYPTO"),
    ("MSTR", "MicroStrategy", "CRYPTO"),
    ("HOOD", "Robinhood", "CRYPTO"),
    ("MARA", "MARA", "MINER"),
    ("RIOT", "Riot", "MINER"),
    ("IBIT", "iShares Bitcoin Trust", "ETF"),
    ("ETHA", "iShares Ethereum Trust", "ETF"),
    ("GBTC", "Grayscale Bitcoin Trust", "ETF"),
    ("SPY", "SPDR S&P 500 ETF", "ETF"),
    ("QQQ", "Invesco QQQ", "ETF"),
    ("XOM", "Exxon Mobil", "ENERGY"),
    ("CVX", "Chevron", "ENERGY"),
    ("GLD", "SPDR Gold Shares", "GOLD"),
    ("USO", "United States Oil Fund", "OIL"),
)


BROKER_NAMES = (
    "Morgan Stanley",
    "Goldman Sachs",
    "JPMorgan",
    "JP Morgan",
    "Bank of America",
    "BofA",
    "Citigroup",
    "Citi",
    "UBS",
    "Deutsche Bank",
    "Wells Fargo",
    "Barclays",
    "Bernstein",
    "Benchmark",
    "Daiwa",
    "Evercore",
    "Jefferies",
    "Mizuho",
    "Melius",
    "Wedbush",
    "Needham",
    "Piper Sandler",
    "RBC",
    "TD Cowen",
    "Oppenheimer",
    "Raymond James",
    "Stifel",
    "Cantor Fitzgerald",
    "KeyBanc",
    "Truist",
    "HSBC",
    "Loop Capital",
    "Rosenblatt",
)


def _field_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(part for part in (_field_text(item) for item in value[:4]) if part)
    if isinstance(value, dict):
        for key in ("name", "displayName", "analystName", "value", "title", "text", "label"):
            if value.get(key) not in (None, ""):
                return _field_text(value.get(key))
        return ""
    return _strip_html(value)


def _setting_tuple(
    ctx: FinanceWatchContext,
    name: str,
) -> tuple[str, ...]:
    dependencies = _dependencies(ctx)
    value = getattr(dependencies.settings, name, ()) if dependencies.settings is not None else ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    try:
        return tuple(str(part).strip() for part in value if str(part).strip())
    except TypeError:
        return ()


def _setting_bool(ctx: FinanceWatchContext, name: str) -> bool:
    dependencies = _dependencies(ctx)
    value = getattr(dependencies.settings, name, False) if dependencies.settings is not None else False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def _broker_research_query() -> str:
    symbols = " OR ".join(symbol for symbol, _name, _theme in BROKER_RESEARCH_SYMBOLS[:18])
    return f'("price target" OR upgrade OR downgrade OR "initiates coverage" OR "top pick" OR reiterates) ({symbols}) when:4d'


def _find_broker_symbol(text: str) -> Optional[tuple[str, str, str]]:
    normalized = f" {text.upper()} "
    for symbol, name, theme in BROKER_RESEARCH_SYMBOLS:
        if re.search(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", normalized):
            return symbol, name, theme
        name_tokens = [token for token in re.split(r"\W+", name.upper()) if len(token) >= 4]
        if name_tokens and all(token in normalized for token in name_tokens[:2]):
            return symbol, name, theme
    return None


def _find_broker_name(text: str, fallback: str) -> str:
    lowered = text.lower()
    for broker in BROKER_NAMES:
        if broker.lower() in lowered:
            return "JPMorgan" if broker == "JP Morgan" else broker
    return fallback or "Research"


def _coalesce_text(*values: Any) -> str:
    for value in values:
        text = _field_text(value)
        if text:
            return text
    return ""


def _coalesce_url(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text.startswith("http://") or text.startswith("https://"):
            return text
    return ""


def _absolute_url(base_url: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.startswith("#") or text.lower().startswith(("javascript:", "mailto:", "tel:")):
        return ""
    return urljoin(base_url, text)


def _extract_anchor_links(html: str, base_url: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for match in re.finditer(r"<a\b[^>]*?\bhref=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</a>", html, flags=re.IGNORECASE):
        href = _absolute_url(base_url, unescape(match.group(1)))
        if not href:
            continue
        label = _strip_html(match.group(2))
        rows.append({"url": href, "label": label})
    return rows


def _research_headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _rss_links(xml_text: str) -> List[Dict[str, str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    rows: List[Dict[str, str]] = []
    for item in root.findall(".//item"):
        url = _coalesce_url(item.findtext("link"), item.findtext("guid"))
        if not url:
            continue
        rows.append({"url": url, "label": _strip_html(item.findtext("title"))})
    return rows


def _extract_html_title(html: str) -> str:
    patterns = (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']title["\'][^>]+content=["\']([^"\']+)["\']',
        r"<h1[^>]*>([\s\S]*?)</h1>",
        r"<title[^>]*>([\s\S]*?)</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return _strip_html(match.group(1))
    return ""


def _extract_html_summary(html: str) -> str:
    patterns = (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r"<p[^>]*>([\s\S]*?)</p>",
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return _strip_html(match.group(1))
    return ""


def _extract_html_published_at(html: str) -> Optional[str]:
    patterns = (
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<time[^>]+datetime=["\']([^"\']+)["\']',
        r"\b(\d{4}-\d{2}-\d{2}T[\d:]+(?:Z|[+-]\d{2}:\d{2})?)\b",
        r"\b(\d{2}/\d{2}/\d{4})\b",
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return _published_iso(match.group(1))
    return None


def _extract_first_pdf_url(html: str, base_url: str) -> str:
    for anchor in _extract_anchor_links(html, base_url):
        url = anchor["url"]
        label = anchor.get("label") or ""
        if ".pdf" in url.lower() or "download pdf" in label.lower() or label.lower().strip() == "pdf":
            return url
    match = re.search(r'https?://[^"\']+?\.pdf(?:\?[^"\']*)?', html, flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _symbol_from_text(text: str) -> str:
    candidates = (
        r"^\s*([A-Z][A-Z0-9.]{1,7})\s*:",
        r"\b(?:NASDAQ|NYSE|NYSEAMERICAN|AMEX|OTC|LON|AIM|TSX|TSXV|ASX|PAR|EPA|FRA|ETR)\s*:\s*([A-Z][A-Z0-9.]{1,7})\b",
        r"\(([A-Z][A-Z0-9.]{1,7})\)",
    )
    blocked = {"PDF", "CEO", "CFO", "FDA", "IPO", "ETF", "USA", "USD", "AI", "Q1", "Q2", "Q3", "Q4"}
    for pattern in candidates:
        match = re.search(pattern, text)
        if match:
            symbol = match.group(1).upper().strip(".")
            if symbol not in blocked and 1 < len(symbol) <= 8:
                return symbol
    return ""


def _normalize_security_code(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).upper().strip()
    if not text:
        return ""
    match = re.search(r"([A-Z]{0,5}\d{3,6}(?:\.[A-Z]{1,4})?|[A-Z][A-Z0-9.:-]{1,11})", text)
    if not match:
        return ""
    code = match.group(1).strip(".:-")
    blocked = {"HTTP", "HTTPS", "REPORT", "RESEARCH", "PDF"}
    return "" if code in blocked else code[:14]


def _broker_number(value: Any) -> Optional[float]:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    return _safe_float(value)


def _dict_value(payload: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    lowered = {str(key).lower(): value for key, value in payload.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _published_iso(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return parsedate_to_datetime(text).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return None


NEWS_OR_AGGREGATOR_DOMAINS = (
    "google.com",
    "news.google.com",
    "benzinga.com",
    "marketbeat.com",
    "thefly.com",
    "tipranks.com",
    "streetinsider.com",
    "investing.com",
    "zacks.com",
    "seekingalpha.com",
    "yahoo.com",
    "finance.yahoo.com",
    "bloomberg.com",
    "reuters.com",
    "cnbc.com",
    "marketwatch.com",
    "barrons.com",
    "wsj.com",
    "fool.com",
)


def _is_news_or_aggregator_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    if not host:
        return True
    return any(host == domain or host.endswith(f".{domain}") for domain in NEWS_OR_AGGREGATOR_DOMAINS)


def _is_original_research_url(url: str, *, allowed_domains: tuple[str, ...] = ()) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    host = (urlparse(url).netloc or "").lower()
    if allowed_domains and any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        return True
    return not _is_news_or_aggregator_url(url)


def _has_known_broker(text: str) -> bool:
    lowered = text.lower()
    return any(broker.lower() in lowered for broker in BROKER_NAMES)


def _broker_action(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if any(word in lowered for word in ("downgrade", "downgrades", "cut to sell", "lowered to underperform")):
        return "DOWNGRADE", "down"
    if any(word in lowered for word in ("upgrade", "upgrades", "raised to buy", "raised to outperform")):
        return "UPGRADE", "up"
    if any(word in lowered for word in ("initiates coverage", "initiate coverage", "started coverage", "starts coverage")):
        return "INITIATE", "watch"
    if any(word in lowered for word in ("top pick", "best idea", "conviction list")):
        return "TOP PICK", "up"
    if any(word in lowered for word in ("raises price target", "raised price target", "boosts price target", "lifts price target", "price target raised", "price target increased")) or re.search(r"\braises\b.{0,40}\bprice target\b", lowered):
        return "PT RAISE", "up"
    if any(word in lowered for word in ("cuts price target", "cut price target", "lowers price target", "lowered price target", "price target cut", "price target lowered")) or re.search(r"\blowers\b.{0,40}\bprice target\b", lowered):
        return "PT CUT", "down"
    if any(word in lowered for word in ("reiterates", "maintains", "keeps")):
        return "REITERATE", "neutral"
    return "NOTE", "neutral"


def _is_broker_research_candidate(text: str, source: str, action: str, target: Optional[float]) -> bool:
    lowered = text.lower()
    product_noise = ("gpu upgrade", "upgrade your", "memory upgrade", "software upgrade", "processor", "driver update", "windows upgrade")
    if any(needle in lowered for needle in product_noise):
        return False
    if target is not None or _has_known_broker(text):
        return True
    source_lower = source.lower()
    if any(needle in source_lower for needle in ("marketbeat", "benzinga", "thefly", "tipranks", "streetinsider", "investing.com")):
        return action in {"UPGRADE", "DOWNGRADE", "INITIATE", "TOP PICK", "PT RAISE", "PT CUT"} and any(needle in lowered for needle in ("analyst", "rating", "price target", "coverage"))
    return False


def _extract_target_prices(text: str) -> tuple[Optional[float], Optional[float]]:
    cleaned = re.sub(r"\s+", " ", text)
    target = None
    previous = None
    target_patterns = (
        r"(?:price target|pt)[^$]{0,48}?\b(?:to|at|of|:)\s*\$([0-9][0-9,]*(?:\.\d+)?)",
        r"\bto\s+\$([0-9][0-9,]*(?:\.\d+)?)\s+from\s+\$([0-9][0-9,]*(?:\.\d+)?)",
        r"\$([0-9][0-9,]*(?:\.\d+)?)\s+(?:price target|pt)",
    )
    for pattern in target_patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if not match:
            continue
        target = _safe_float(match.group(1).replace(",", ""))
        if len(match.groups()) >= 2:
            previous = _safe_float(match.group(2).replace(",", ""))
        break
    if previous is None:
        from_match = re.search(r"\bfrom\s+\$([0-9][0-9,]*(?:\.\d+)?)", cleaned, flags=re.IGNORECASE)
        previous = _safe_float(from_match.group(1).replace(",", "")) if from_match else None
    return target, previous


def _broker_priority(action: str, upside: Optional[float], target_change: Optional[float], published_at: Optional[str], symbol: str) -> float:
    action_score = {
        "UPGRADE": 42,
        "DOWNGRADE": 42,
        "INITIATE": 34,
        "TOP PICK": 32,
        "PT RAISE": 26,
        "PT CUT": 26,
        "REITERATE": 12,
    }.get(action, 8)
    recency = 0.0
    if published_at:
        try:
            age_hours = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(published_at.replace("Z", "+00:00"))).total_seconds() / 3600)
            recency = max(0.0, 30.0 - age_hours)
        except ValueError:
            recency = 0.0
    importance = 16 if symbol in {"NVDA", "AMD", "MSFT", "TSLA", "COIN", "MSTR", "AAPL", "META"} else 8
    return action_score + recency + importance + min(22.0, abs(upside or 0.0)) + min(18.0, abs(target_change or 0.0))


def _broker_research_row(
    ctx: FinanceWatchContext,
    *,
    title: str,
    summary: str,
    report_url: str,
    source: str,
    published_at: Optional[str],
    quote_cache: Dict[str, Dict[str, Any]],
    explicit_symbol: str = "",
    explicit_company: str = "",
    explicit_target: Any = None,
    explicit_previous_target: Any = None,
    explicit_action: str = "",
    explicit_rating: str = "",
    explicit_analyst: str = "",
) -> Optional[Dict[str, Any]]:
    text = f"{title} {summary} {explicit_symbol}"
    match = _find_broker_symbol(text)
    if match:
        symbol, company, theme = match
    else:
        symbol = _normalize_security_code(explicit_symbol) or _symbol_from_text(f"{explicit_symbol} {title} {summary}")
        if not symbol:
            return None
        company = explicit_company or symbol
        theme = "RESEARCH"
    if explicit_company:
        company = explicit_company
    title = title or f"{symbol} broker research"
    summary = summary or title
    broker = _find_broker_name(text, source)
    action, action_tone = _broker_action(f"{explicit_action} {text}")
    target, previous_target = _extract_target_prices(text)
    target = _broker_number(explicit_target) if explicit_target not in (None, "") else target
    previous_target = _broker_number(explicit_previous_target) if explicit_previous_target not in (None, "") else previous_target
    target_change = ((target - previous_target) / previous_target * 100) if target is not None and previous_target not in (None, 0) else None
    rating_label = _coalesce_text(explicit_rating, explicit_action, action).upper()
    if rating_label in {"NOTE", "REPORT"}:
        rating_label = "REPORT"
    tags = [rating_label, "REPORT", theme]
    if target_change is not None:
        tags[0] = "PT RAISE" if target_change > 0 else "PT CUT" if target_change < 0 else action
    tone = "up" if action_tone == "up" else "down" if action_tone == "down" else "watch" if action_tone == "watch" else "neutral"
    target_label = f"PT {_format_price(target)}" if target is not None else "PT --"
    analyst = _coalesce_text(explicit_analyst)
    summary_bits = [broker, company]
    if analyst:
        summary_bits.append(analyst)
    if rating_label and rating_label != "REPORT":
        summary_bits.append(rating_label.title())
    if target is not None:
        summary_bits.append(target_label)
    if previous_target is not None:
        summary_bits.append(f"from {_format_price(previous_target)}")
    return {
        "id": f"broker-research:{symbol}:{abs(hash(report_url or title))}",
        "label": symbol,
        "symbol": company.upper()[:16],
        "title": title,
        "summary": " | ".join(summary_bits),
        "source": broker,
        "url": report_url,
        "publishedAt": published_at,
        "metric": target,
        "metricLabel": rating_label,
        "metricUnit": "RATING",
        "secondary": target,
        "secondaryLabel": target_label,
        "change": target_change,
        "changeLabel": f"{target_change:+.1f}% PT" if target_change is not None else None,
        "tags": tags[:3],
        "tone": tone,
        "points": [],
        "company": company,
        "institution": broker,
        "analyst": analyst,
        "rating": rating_label,
        "targetPriceLabel": target_label,
        "previousTargetPriceLabel": f"FROM {_format_price(previous_target)}" if previous_target is not None else None,
        "reportPageLabel": "Read report",
        "_priority": _broker_priority(action, None, target_change, published_at, symbol),
    }


def _extract_json_research_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "reports", "research", "analystActions", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _candidate_links_for_provider(provider: str, html: str, source_url: str, limit: int) -> List[Dict[str, str]]:
    provider_key = provider.lower()
    rows: List[Dict[str, str]] = []
    seen = set()
    for anchor in _extract_anchor_links(html, source_url):
        url = anchor["url"]
        label = anchor.get("label") or ""
        lower_url = url.lower()
        lower_label = label.lower()
        keep = False
        if provider_key == "edison":
            keep = (
                "edisongroup.com" in lower_url
                and ("/research/" in lower_url or "/insight/" in lower_url or ".pdf" in lower_url)
                and "/equity-research" not in lower_url
            )
        elif provider_key.startswith("zacks"):
            keep = (
                "scr.zacks.com" in lower_url
                and ("/news/news-details/" in lower_url or "/files/news/" in lower_url or ".pdf" in lower_url)
            )
        elif provider_key in {"water tower", "watertower"}:
            keep = (
                "watertowerresearch.com" in lower_url
                and ("/research" in lower_url or "/content/" in lower_url or "/reports/" in lower_url or ".pdf" in lower_url)
                and "login" not in lower_url
            )
        elif provider_key in {"eastmoney", "choice"}:
            keep = (
                ("eastmoney.com" in lower_url or "dfcfw.com" in lower_url)
                and any(word in lower_url or word in lower_label for word in ("report", "research", "yanbao", "研报", "评级", "目标价"))
            )
        else:
            keep = any(word in lower_url or word in lower_label for word in ("research", "report", "pdf"))
        if keep and url not in seen:
            rows.append(anchor)
            seen.add(url)
        if len(rows) >= limit:
            break
    return rows


def _open_research_sources(
    ctx: FinanceWatchContext,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    sources = (
        ("Eastmoney", _setting(ctx, "finance_broker_research_eastmoney_url"), ("eastmoney.com", "eastmoney.com.cn", "dfcfw.com")),
        ("Choice", _setting(ctx, "finance_broker_research_choice_url"), ("eastmoney.com", "eastmoney.com.cn", "dfcfw.com")),
        ("Edison", _setting(ctx, "finance_broker_research_edison_url"), ("edisongroup.com",)),
        ("Zacks SCR", _setting(ctx, "finance_broker_research_zacks_url"), ("scr.zacks.com",)),
        ("Water Tower", _setting(ctx, "finance_broker_research_water_tower_url"), ("watertowerresearch.com",)),
    )
    return tuple((name, url, domains) for name, url, domains in sources if url)


def _build_broker_rows_from_open_sources(
    ctx: FinanceWatchContext,
    *,
    limit: int,
    rows: List[Dict[str, Any]],
    sources: Dict[str, str],
    quote_cache: Dict[str, Dict[str, Any]],
    seen_urls: set,
) -> None:
    max_candidates_per_source = max(4, min(10, limit))
    for provider, source_url, allowed_domains in _open_research_sources(ctx):
        source_key = provider
        try:
            listing_html = _http_text_get(ctx, source_url, timeout=16, headers=_research_headers())
        except Exception:
            sources[source_key] = "error"
            continue
        stripped_listing = listing_html.lstrip()
        candidates = _rss_links(stripped_listing) if stripped_listing.startswith("<?xml") or stripped_listing.startswith("<rss") else _candidate_links_for_provider(provider, listing_html, source_url, max_candidates_per_source)
        candidates = candidates[:max_candidates_per_source]
        parsed_count = 0
        for candidate in candidates:
            candidate_url = candidate["url"]
            detail_html = ""
            report_url = candidate_url
            keep_detail_page = provider.lower() in {"eastmoney", "choice"}
            if ".pdf" not in candidate_url.lower():
                try:
                    detail_html = _http_text_get(ctx, candidate_url, timeout=12, headers=_research_headers())
                except Exception:
                    detail_html = ""
                pdf_url = "" if keep_detail_page else (_extract_first_pdf_url(detail_html, candidate_url) if detail_html else "")
                if pdf_url:
                    report_url = pdf_url
            if not _is_original_research_url(report_url, allowed_domains=allowed_domains) or report_url in seen_urls:
                continue
            page_text = detail_html or listing_html
            title = _extract_html_title(page_text)
            if title.lower().strip() in {"news details", "zacks small cap research - news details"}:
                title = ""
            title = title or candidate.get("label") or f"{provider} research report"
            summary = _extract_html_summary(page_text)
            published_at = _extract_html_published_at(page_text)
            symbol = _symbol_from_text(f"{title} {summary} {candidate_url} {report_url}")
            row = _broker_research_row(
                ctx,
                title=title,
                summary=summary,
                report_url=report_url,
                source=provider,
                published_at=published_at,
                quote_cache=quote_cache,
                explicit_symbol=symbol,
            )
            if row:
                rows.append(row)
                seen_urls.add(report_url)
                parsed_count += 1
            if len(rows) >= max(limit * 2, 18):
                break
        sources[source_key] = "ok" if parsed_count else ("empty" if candidates else "no-links")


def _build_broker_rows_from_configured_sources(
    ctx: FinanceWatchContext,
    limit: int,
) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
    rows: List[Dict[str, Any]] = []
    sources: Dict[str, str] = {}
    quote_cache: Dict[str, Dict[str, Any]] = {}
    seen_urls = set()
    for source_url in _setting_tuple(ctx, "finance_broker_research_feed_urls"):
        source_key = urlparse(source_url).netloc or source_url
        try:
            raw_text = _http_text_get(ctx, source_url, timeout=16)
        except Exception:
            sources[source_key] = "error"
            continue
        parsed_count = 0
        stripped = raw_text.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                sources[source_key] = "parse-error"
                continue
            for item in _extract_json_research_items(payload):
                report_url = _coalesce_url(
                    _dict_value(
                        item,
                        "reportPageUrl",
                        "eastmoneyUrl",
                        "choiceUrl",
                        "originalUrl",
                        "sourceUrl",
                        "pageUrl",
                        "detailUrl",
                        "researchUrl",
                        "url",
                        "link",
                        "reportUrl",
                        "pdfUrl",
                        "documentUrl",
                    )
                )
                if not _is_original_research_url(report_url) or report_url in seen_urls:
                    continue
                row = _broker_research_row(
                    ctx,
                    title=_coalesce_text(_dict_value(item, "title", "headline", "reportTitle", "reportName", "researchTitle", "name")),
                    summary=_coalesce_text(_dict_value(item, "summary", "abstract", "description", "body")),
                    report_url=report_url,
                    source=_coalesce_text(_dict_value(item, "institution", "researchInstitution", "orgName", "orgSName", "broker", "brokerName", "firm", "source", "publisher", "provider")),
                    published_at=_published_iso(_dict_value(item, "publishedAt", "published", "publishDate", "publishTime", "reportDate", "noticeDate", "date", "createdAt", "time")),
                    quote_cache=quote_cache,
                    explicit_symbol=_coalesce_text(_dict_value(item, "symbol", "ticker", "ric", "securityCode", "secuCode", "stockCode", "code")),
                    explicit_company=_coalesce_text(_dict_value(item, "company", "companyName", "securityName", "stockName", "secuName")),
                    explicit_target=_dict_value(item, "targetPrice", "priceTarget", "pt"),
                    explicit_previous_target=_dict_value(item, "previousTargetPrice", "previousPriceTarget", "previousPt"),
                    explicit_action=_coalesce_text(_dict_value(item, "action", "ratingAction", "recommendation", "rating")),
                    explicit_rating=_coalesce_text(_dict_value(item, "rating", "ratingName", "investmentRating", "recommendation")),
                    explicit_analyst=_coalesce_text(_dict_value(item, "analyst", "analystName", "analysts", "author", "researcher", "researchAuthors")),
                )
                if row:
                    rows.append(row)
                    seen_urls.add(report_url)
                    parsed_count += 1
        else:
            try:
                root = ElementTree.fromstring(raw_text)
            except ElementTree.ParseError:
                sources[source_key] = "parse-error"
                continue
            for item in root.findall(".//item")[: max(20, limit * 5)]:
                report_url = _coalesce_url(item.findtext("link"), item.findtext("guid"))
                if not _is_original_research_url(report_url) or report_url in seen_urls:
                    continue
                row = _broker_research_row(
                    ctx,
                    title=_strip_html(item.findtext("title")),
                    summary=_strip_html(item.findtext("description")),
                    report_url=report_url,
                    source=_compact_source(item.findtext("source") or source_key),
                    published_at=_published_iso(item.findtext("pubDate")),
                    quote_cache=quote_cache,
                )
                if row:
                    rows.append(row)
                    seen_urls.add(report_url)
                    parsed_count += 1
        sources[source_key] = "ok" if parsed_count else "empty"
    _build_broker_rows_from_open_sources(ctx, limit=limit, rows=rows, sources=sources, quote_cache=quote_cache, seen_urls=seen_urls)
    rows.sort(key=lambda row: _safe_float(row.get("_priority")) or 0.0, reverse=True)
    for row in rows:
        row.pop("_priority", None)
    return rows[:limit], sources


def _build_broker_research_news_fallback(
    ctx: FinanceWatchContext,
    limit: int,
) -> Dict[str, Any]:
    try:
        xml_text = _http_text_get(ctx, _news_url(ctx, _broker_research_query()), timeout=14)
    except Exception as exc:
        return _payload("broker-research-watch", title="BROKER RESEARCH", items=[], status="error", sources={"googleNews": "error"}, summary={"error": str(exc)})
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return _payload("broker-research-watch", title="BROKER RESEARCH", items=[], status="empty", sources={"googleNews": "parse-error"})

    rows: List[Dict[str, Any]] = []
    seen_titles = set()
    quote_cache: Dict[str, Dict[str, Any]] = {}
    for item in root.findall(".//item")[: max(12, limit * 4)]:
        title = _strip_html(item.findtext("title"))
        description = _strip_html(item.findtext("description"))
        source = _compact_source(item.findtext("source") or "Google News")
        text = f"{title} {description}"
        match = _find_broker_symbol(text)
        if not match or title in seen_titles:
            continue
        seen_titles.add(title)
        symbol, company, theme = match
        broker = _find_broker_name(text, source)
        action, action_tone = _broker_action(text)
        target, previous_target = _extract_target_prices(text)
        if not _is_broker_research_candidate(text, source, action, target):
            continue
        if symbol not in quote_cache:
            quote_cache[symbol] = _fetch_yahoo_snapshot(ctx, symbol, interval="30m", range_name="5d") or {}
        quote = quote_cache.get(symbol) or {}
        current_price = _safe_float(quote.get("price"))
        upside = ((target - current_price) / current_price * 100) if target is not None and current_price not in (None, 0) else None
        target_change = ((target - previous_target) / previous_target * 100) if target is not None and previous_target not in (None, 0) else None
        published_raw = item.findtext("pubDate")
        published_at = None
        if published_raw:
            try:
                published_at = parsedate_to_datetime(published_raw).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except (TypeError, ValueError):
                published_at = None
        tags = [action]
        if target_change is not None:
            price_target_tag = "PT RAISE" if target_change > 0 else "PT CUT" if target_change < 0 else "PT"
            if price_target_tag not in tags:
                tags.append(price_target_tag)
        tags.append(theme)
        tone = "up" if (upside is not None and upside > 0) or action_tone == "up" else "down" if (upside is not None and upside < 0) or action_tone == "down" else "watch" if action_tone == "watch" else "neutral"
        target_label = f"PT {_format_price(target)}" if target is not None else (_format_price(current_price) if current_price is not None else "--")
        metric_label = f"{upside:+.1f}%" if upside is not None else target_label
        summary_bits = [broker, action.replace("PT ", "target ")]
        if target is not None:
            summary_bits.append(f"target {target_label}")
        if previous_target is not None:
            summary_bits.append(f"from {_format_price(previous_target)}")
        if current_price is not None:
            summary_bits.append(f"spot {_format_price(current_price)}")
        rows.append(
            {
                "id": f"broker-research:{symbol}:{abs(hash(title))}",
                "label": symbol,
                "symbol": company.upper()[:16],
                "title": title,
                "summary": " | ".join(summary_bits),
                "source": broker,
                "url": item.findtext("link"),
                "publishedAt": published_at,
                "metric": upside,
                "metricLabel": metric_label,
                "metricUnit": "UPSIDE",
                "secondary": target,
                "secondaryLabel": target_label,
                "change": target_change,
                "changeLabel": f"{target_change:+.1f}% PT" if target_change is not None else (_format_pct(quote.get("changePercent")) if quote.get("changePercent") is not None else None),
                "tags": tags[:3],
                "tone": tone,
                "points": quote.get("points") or [],
                "_priority": _broker_priority(action, upside, target_change, published_at, symbol),
            }
        )
        if len(rows) >= max(limit * 2, 18):
            break
    rows.sort(key=lambda row: _safe_float(row.get("_priority")) or 0.0, reverse=True)
    for row in rows:
        row.pop("_priority", None)
    upgrades = sum(1 for row in rows if "UPGRADE" in (row.get("tags") or []))
    cuts = sum(1 for row in rows if any(tag in {"DOWNGRADE", "PT CUT"} for tag in (row.get("tags") or [])))
    return _payload(
        "broker-research-watch",
        title="BROKER RESEARCH",
        items=rows[:limit],
        summary={"upgrades": upgrades, "cuts": cuts, "topSymbol": rows[0]["label"] if rows else None, "rankBy": "rating action + target revision + recency"},
        sources={"googleNewsFallback": "ok" if rows else "empty", "yahoo": "ok" if quote_cache else "empty"},
    )


def build_broker_research_payload(
    ctx: FinanceWatchContext,
    limit: int,
) -> Dict[str, Any]:
    rows, sources = _build_broker_rows_from_configured_sources(ctx, limit)
    if rows:
        upgrades = sum(1 for row in rows if "UPGRADE" in (row.get("tags") or []))
        cuts = sum(1 for row in rows if any(tag in {"DOWNGRADE", "PT CUT"} for tag in (row.get("tags") or [])))
        return _payload(
            "broker-research-watch",
            title="BROKER RESEARCH",
            items=rows,
            summary={"upgrades": upgrades, "cuts": cuts, "topSymbol": rows[0]["label"], "rankBy": "original report + target revision + recency"},
            sources=sources or {"brokerResearchFeeds": "empty"},
        )
    if _setting_bool(ctx, "finance_broker_research_news_fallback"):
        return _build_broker_research_news_fallback(ctx, limit)
    return _payload(
        "broker-research-watch",
        title="BROKER RESEARCH",
        items=[],
        status="empty",
        summary={
            "reason": "No original broker research metadata source produced rows",
            "requiredEnv": "POLYDATA_FINANCE_BROKER_RESEARCH_FEED_URLS or POLYDATA_FINANCE_BROKER_RESEARCH_EASTMONEY_URL / POLYDATA_FINANCE_BROKER_RESEARCH_CHOICE_URL",
        },
        sources=sources or {"brokerResearchFeeds": "missing"},
    )
