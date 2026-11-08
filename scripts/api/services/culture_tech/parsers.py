"""Public culture/technology evidence. No provider endpoint defaults live here."""
from __future__ import annotations

import io
import json
import math
import re
import zipfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from api.services.panel_evidence_store import public_url


def text(value, limit=600):
    return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True))[:limit]


def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            date = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            return None
    return date.replace(tzinfo=date.tzinfo or timezone.utc).isoformat()


def arena(raw):
    data = json.loads(raw)
    rows = []
    for wrapped in data.get("rows", []):
        r = wrapped.get("row", {})
        if r.get("category") != "overall" or number(r.get("rating")) is None:
            continue
        rows.append({"id": text(r.get("model_name")), "title": text(r.get("model_name")),
            "organization": text(r.get("organization")), "score": number(r.get("rating")),
            "lower": number(r.get("rating_lower")), "upper": number(r.get("rating_upper")),
            "votes": number(r.get("vote_count")), "rank": number(r.get("rank")),
            "publishedAt": r.get("leaderboard_publish_date"), "category": "overall", "subset": "text"})
    if not rows:
        raise ValueError("No valid overall Text Arena rows")
    return {"items": sorted(rows, key=lambda r: r["rank"] or 10000)[:100],
        "coverage": "Arena · Text / Overall · published top-100 sample · CC BY 4.0. Not style controlled; no derived rank intervals.",
        "publishedAt": rows[0]["publishedAt"]}


def music(raw):
    feed = json.loads(raw)["feed"]
    rows = [{"id": str(r["id"]), "title": text(r["name"]), "artist": text(r.get("artistName")),
        "rank": i + 1, "releasedAt": r.get("releaseDate"), "url": public_url(r.get("url")),
        "genre": text(next((g["name"] for g in r.get("genres", []) if g.get("name") != "Music"), ""))}
        for i, r in enumerate(feed.get("results", [])[:100]) if r.get("id") and r.get("name")]
    return {"items": rows, "publishedAt": timestamp(feed.get("updated")), "country": feed.get("country"),
        "coverage": "Apple Music · US most-played songs. Chart order, not stream counts or Billboard rank."}


def launches(raw):
    data = json.loads(raw)
    rows = []
    for r in data.get("results", [])[:30]:
        mission = r.get("mission") or {}
        status = r.get("status") or {}
        rows.append({"id": str(r["id"]), "title": text(r.get("name")), "url": public_url(r.get("url")),
            "status": text(status.get("name")), "statusDescription": text(status.get("description")),
            "windowStart": timestamp(r.get("window_start")), "windowEnd": timestamp(r.get("window_end")),
            "eventTime": timestamp(r.get("net")), "publishedAt": timestamp(r.get("last_updated")),
            "precision": text((r.get("net_precision") or {}).get("name")),
            "operator": text((r.get("launch_service_provider") or {}).get("name")),
            "location": text((r.get("pad") or {}).get("name")), "mission": text(mission.get("description")),
            "orbit": text((mission.get("orbit") or {}).get("name"))})
    return {"items": rows, "coverage": "Launch Library 2 schedule / source-reported status. Planned windows are not launch confirmation; no live telemetry."}


def research(raw):
    data = json.loads(raw)
    rows = []
    for r in data["message"]["items"][:50]:
        parts = (r.get("published") or {}).get("date-parts", [[]])[0]
        date = "-".join(str(n).zfill(4 if i == 0 else 2) for i, n in enumerate(parts)) or None
        title = text((r.get("title") or [""])[0])
        if not re.search(r"artificial intelligence|machine learning|large language|deep learning", title, re.I):
            continue
        if not r.get("DOI") or not date or date > datetime.now(timezone.utc).date().isoformat():
            continue
        rows.append({"id": text(r.get("DOI")), "title": text((r.get("title") or [""])[0]),
            "url": public_url(r.get("URL")), "publishedAt": date, "kind": text(r.get("type")),
            "publisher": text(r.get("publisher")), "journal": text((r.get("container-title") or [""])[0]),
            "citations": number(r.get("is-referenced-by-count")),
            "updatedAt": timestamp((r.get("indexed") or {}).get("date-time"))})
    if not rows:
        raise ValueError("No published AI research with valid identity/date")
    return {"items": rows, "coverage": "Crossref DOI metadata · bounded AI title search, future dates excluded. A registered journal article does not verify a breakthrough, peer-review quality or clinical efficacy."}


def steam(raw):
    data = json.loads(raw)
    rows = []
    for group in ("new_releases", "coming_soon"):
        for r in (data.get(group) or {}).get("items", [])[:30]:
            if not r.get("id") or not r.get("name"):
                continue
            rows.append({"id": str(r["id"]), "title": text(r["name"]),
                "stage": "New release listing" if group == "new_releases" else "Coming soon listing",
                "currency": text(r.get("currency")), "priceMinor": number(r.get("final_price")),
                "windows": r.get("windows_available"), "mac": r.get("mac_available"),
                "linux": r.get("linux_available"), "discountPercent": number(r.get("discount_percent")),
                "releasedAt": None})
    if not rows:
        raise ValueError("Steam release categories missing")
    return {"items": rows, "coverage": "Steam US storefront · new-release / coming-soon listings. Listing status is not evidence of a specific 1.0 release date; prices retain currency minor units."}


def auctions(raw):
    soup = BeautifulSoup(raw, "html.parser")
    rows = []
    for script in soup.find_all("script", type="application/ld+json"):
        data = json.loads(script.get_text())
        graph = data.get("@graph", [data]) if isinstance(data, dict) else data
        for r in graph:
            if r.get("@type") != "Event" or not public_url(r.get("url")):
                continue
            rows.append({"id": r.get("@id") or r["url"], "title": text(r.get("name")),
                "url": public_url(r["url"]), "eventTime": r.get("startDate"), "endDate": r.get("endDate"),
                "location": text((r.get("location") or {}).get("name")), "house": "Christie's",
                "estimateLow": None, "estimateHigh": None, "hammer": None})
    if not rows:
        raise ValueError("Auction calendar schema missing")
    return {"items": rows[:60], "coverage": "Christie's official sale calendar. Lot estimates, hammer prices, buyer premiums and authentication are not supplied by this calendar."}


def reality(raw):
    data = json.loads(raw)
    episodes = data.get("_embedded", {}).get("episodes", [])
    season = max((int(r.get("season") or 0) for r in episodes), default=0)
    rows = [{"id": str(r["id"]), "title": text(r.get("name")), "season": r.get("season"),
        "episode": r.get("number"), "eventTime": timestamp(r.get("airstamp")), "runtime": r.get("runtime"),
        "url": public_url(r.get("url")), "elimination": None}
        for r in episodes if r.get("season") == season][:60]
    return {"items": rows, "show": text(data.get("name")), "season": season,
        "network": text((data.get("network") or {}).get("name")),
        "coverage": "TVmaze · latest listed Survivor season / episode schedule · CC BY-SA. Third-party metadata; contestants, vote windows and elimination outcomes require official evidence."}


def speeches(raw):
    root = ET.fromstring(raw)
    rows = []
    for r in root.findall(".//item")[:15]:
        title = text(r.findtext("title"))
        rows.append({"id": r.findtext("guid") or r.findtext("link"), "title": title,
            "speaker": re.split(r"[:,]", title, maxsplit=1)[0] if re.search(r"[:,]", title) else None,
            "publishedAt": timestamp(r.findtext("pubDate")), "url": public_url(r.findtext("link")),
            "kind": "Published remarks", "transcript": None})
    if not rows:
        raise ValueError("Speech feed missing items")
    return {"items": rows, "coverage": "Federal Reserve official published remarks. Publication is not proof of unscripted speech, an appearance schedule or a complete recording."}


def transcript(raw):
    soup = BeautifulSoup(raw, "html.parser")
    main = soup.select_one("#article") or soup.select_one("main")
    if main is None:
        raise ValueError("Official speech article not found")
    paragraphs = [text(p.get_text(" ", strip=True), 5000) for p in main.select("p")]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    if sum(map(len, paragraphs)) < 300:
        raise ValueError("Speech body is incomplete")
    bounded, size = [], 0
    for paragraph in paragraphs[:120]:
        if size + len(paragraph) > 50000:
            break
        bounded.append(paragraph)
        size += len(paragraph)
    return bounded


def social(raw):
    data = json.loads(raw)
    if not isinstance(data.get("feed"), list):
        raise ValueError("Social feed missing")
    rows = []
    for item in data["feed"][:50]:
        if item.get("reason"):
            continue
        p = item.get("post") or {}
        record = p.get("record") or {}
        author = p.get("author") or {}
        labels = [x.get("val") for x in [*author.get("labels", []), *p.get("labels", [])]]
        if any(v in {"!no-unauthenticated", "!hide", "!warn", "porn", "sexual", "graphic-media"} for v in labels):
            continue
        # Feed reposts and replies remain labelled; no fabricated complete-window count.
        rows.append({"id": p.get("uri"), "title": text(record.get("text"), 300),
            "author": text(author.get("handle")), "displayName": text(author.get("displayName")),
            "publishedAt": timestamp(record.get("createdAt")), "likes": number(p.get("likeCount")),
            "reposts": number(p.get("repostCount")), "replies": number(p.get("replyCount")),
            "kind": "Repost" if item.get("reason") else "Reply" if record.get("reply") else "Post"})
    return {"items": rows, "hasMore": bool(data.get("cursor")),
        "coverage": "Bluesky configured public profile · recent eligible original posts/replies, excluding reposts and restricted labels. Counters are observed snapshots, not full-window totals; X is not covered."}


def box_office(raw):
    namespaces = {"t": "urn:oasis:names:tc:opendocument:xmlns:table:1.0"}
    office = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
    table = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.getinfo("content.xml")
        if info.file_size > 4 * 1024**2:
            raise ValueError("Box office spreadsheet expanded size exceeded")
        xml = ET.fromstring(archive.read(info))
    rows, period = [], ""
    for row in xml.findall(".//t:table-row", namespaces)[:200]:
        cells = []
        for c in list(row):
            value = c.attrib.get(office + "value")
            v = number(value) if value is not None else text(" ".join(c.itertext()))
            cells.extend([v] * min(12 - len(cells), int(c.attrib.get(table + "number-columns-repeated", 1))))
            if len(cells) >= 12:
                break
        if cells and isinstance(cells[0], str) and "BFI Weekend Box Office" in cells[0]:
            period = cells[0].replace("BFI Weekend Box Office", "").strip()
        if len(cells) >= 10 and isinstance(cells[0], (int, float)) and 0 < cells[0] <= 100 and isinstance(cells[1], str):
            rows.append({"id": cells[1] + "/" + period, "title": cells[1], "rank": cells[0],
                "gross": number(cells[3]), "totalGross": number(cells[9]), "cinemas": number(cells[7]),
                "weeks": number(cells[6]), "change": number(cells[5]), "distributor": cells[4], "currency": "GBP"})
    if not rows or not period:
        raise ValueError("BFI spreadsheet schema missing")
    return {"items": rows[:100], "period": period, "currency": "GBP", "territory": "UK",
        "coverage": "BFI UK weekend gross · GBP · Friday–Sunday. Includes published revisions and preview treatment; not North American or worldwide box office."}
