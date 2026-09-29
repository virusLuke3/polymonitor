from __future__ import annotations

import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List
from xml.etree import ElementTree

from api.services.finance_watch.common import (
    FinanceWatchContext,
    _compact_source,
    _http_text_get,
    _news_url,
    _payload,
    _strip_html,
)

NEWS_QUERIES = {
    "defi-security-watch": '("DeFi" OR "crypto protocol") (exploit OR hack OR vulnerability OR attack OR audit OR governance risk)',
    "ipo-news-watch": 'IPO OR "S-1" OR "F-1" OR "files for listing" OR "public listing" OR "listing rumor"',
    "blockchain-policy-news": '("crypto bill" OR "stablecoin legislation" OR "SEC crypto" OR "CFTC crypto" OR "exchange enforcement" OR "tokenization regulation")',
}


def _parse_rss_items(xml_text: str, *, panel_id: str, limit: int) -> List[Dict[str, Any]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    rows: List[Dict[str, Any]] = []
    for item in root.findall(".//item")[: max(1, limit * 2)]:
        title = _strip_html(item.findtext("title"))
        description = _strip_html(item.findtext("description"))
        source = _compact_source(item.findtext("source") or "Google News")
        link = item.findtext("link")
        published_raw = item.findtext("pubDate")
        published_at = None
        if published_raw:
            try:
                published_at = parsedate_to_datetime(published_raw).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except (TypeError, ValueError):
                published_at = None
        tags = _news_tags(panel_id, title, description)
        rows.append(
            {
                "id": f"{panel_id}:{len(rows)}:{hash(title)}",
                "label": _headline_entity(title, source),
                "symbol": source.upper()[:14],
                "title": title,
                "summary": description,
                "source": source,
                "url": link,
                "publishedAt": published_at,
                "tags": tags,
                "tone": "down" if any(tag in {"HACK", "EXPLOIT", "ALERT", "ENFORCE"} for tag in tags) else "neutral",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _headline_entity(title: str, source: str) -> str:
    cleaned = re.split(r"\s[-|]\s", title or "")[0].strip()
    words = cleaned.split()
    if len(words) >= 2:
        return " ".join(words[:3])[:28]
    return cleaned[:28] or source


def _news_tags(panel_id: str, title: str, description: str) -> List[str]:
    text = f"{title} {description}".lower()
    pairs = (
        ("HACK", ("hack", "hacked", "drain")),
        ("EXPLOIT", ("exploit", "attack", "breach")),
        ("ALERT", ("vulnerability", "warning", "risk")),
        ("AUDIT", ("audit", "auditor")),
        ("S-1", ("s-1", "s1")),
        ("F-1", ("f-1", "f1")),
        ("IPO", ("ipo", "initial public")),
        ("LISTING", ("listing", "go public")),
        ("RUMOR", ("rumor", "reportedly")),
        ("BILL", ("bill", "legislation", "lawmakers")),
        ("SEC", ("sec", "securities and exchange")),
        ("CFTC", ("cftc",)),
        ("COURT", ("court", "judge", "lawsuit")),
        ("ENFORCE", ("enforcement", "charged", "settlement")),
        ("STABLE", ("stablecoin",)),
        ("GOV", ("governance", "proposal", "dao")),
        ("BRIDGE", ("bridge", "cross-chain", "cross chain")),
    )
    tags = [label for label, needles in pairs if any(needle in text for needle in needles)]
    if panel_id == "defi-security-watch":
        return (tags or ["ALERT"])[:3]
    if panel_id == "ipo-news-watch":
        return (tags or ["IPO"])[:3]
    return (tags or ["POLICY"])[:3]


def build_news_payload(
    ctx: FinanceWatchContext,
    panel_id: str,
    title: str,
    limit: int,
) -> Dict[str, Any]:
    query = NEWS_QUERIES[panel_id]
    xml_text = _http_text_get(ctx, _news_url(ctx, query), timeout=16)
    rows = _parse_rss_items(xml_text, panel_id=panel_id, limit=limit)
    return _payload(panel_id, title=title, items=rows, summary={"query": query}, sources={"googleNewsRss": "ok" if rows else "empty"})
