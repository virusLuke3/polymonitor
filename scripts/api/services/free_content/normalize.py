from __future__ import annotations
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "blockquote", "iframe", "svg"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li"} and not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "blockquote", "iframe", "svg"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = TextOnly()
    parser.feed(str(value or ""))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def utc(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000, timezone.utc)
        else:
            try:
                stamp = str(value).strip().replace("Z", "+00:00")
                # Python 3.10 requires 3/6 fractional digits; Atom permits any precision.
                stamp = re.sub(r"(T\d{2}:\d{2}:\d{2})\.(\d+)", lambda m: m[1] + "." + m[2].ljust(6, "0")[:6], stamp)
                dt = datetime.fromisoformat(stamp)
            except ValueError:
                dt = parsedate_to_datetime(str(value))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError):
        return None


def canonical_url(value, source):
    parsed = urlsplit(str(value or "").strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in source["allowed_hosts"]
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        return None
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    return urlunsplit(("https", parsed.hostname, re.sub("/{2,}", "/", parsed.path), urlencode(query), "")).rstrip(" #")


def identity(source, item):
    # URL is the cross-feed article identity; event identity survives revisions.
    key = item.get("event_id") or item["url"]
    return "free:" + hashlib.sha256((source["publisher_id"] + ":" + key).encode()).hexdigest()[:40]


def permission(source, item):
    if (
        not source.get("enabled")
        or source.get("probe_status") != "passed"
        or not source.get("policy_checked_at")
        or not source.get("display_title_allowed")
    ):
        return False, "policy-unknown"
    if not canonical_url(item.get("url"), source):
        return False, "unapproved-article-host"
    text = item.get("rights_text", "").lower()
    if any(
        marker in text
        for marker in (
            "all rights reserved",
            "republished with permission",
            "reproduced with permission",
            "copyright-protected",
            "different license",
            "© dialogue earth",
        )
    ):
        return False, "special-rights"
    if source["publisher_id"] == "global-voices":
        if not item.get("author"):
            return False, "required-author-missing"
        if any(
            name in item["author"].lower()
            for name in ("dialogue earth", "the conversation", "open democracy", "occrp", "african arguments")
        ):
            return False, "third-party-republication"
        if not item.get("article_rights_checked"):
            return False, "article-rights-unverified"
    if source["publisher_id"] == "ecb":
        if "/press/pr/date/" not in item["url"] or item.get("author"):
            return False, "not-institutional-press-release"
    if source["publisher_id"] == "nasa" and "/news-release/" not in item["url"]:
        return False, "not-nasa-news-release"
    if source["publisher_id"] == "nhc" and not str(item.get("event_id", "")).startswith("nhc:"):
        return False, "event-identity-unverified"
    if source["source_kind"] == "alert":
        if item.get("status") != "Actual" or item.get("message_type") == "Cancel":
            return False, "non-active-alert"
    return True, "approved"


def parse_feed(body, source):
    # RSS HTML can contain declaration-like text inside CDATA/comments. Those
    # are not XML declarations; reject only markup that the XML parser sees.
    markup = re.sub(rb"<!\[CDATA\[.*?\]\]>|<!--.*?-->", b"", body, flags=re.S)
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", markup, re.I):
        raise ValueError("xml-entities-forbidden")
    root = ET.fromstring(body)
    local = lambda tag: tag.rsplit("}", 1)[-1]
    if local(root.tag) not in {"rss", "feed", "RDF"}:
        raise ValueError("not-rss-or-atom")
    items = []
    for entry in root.iter():
        if local(entry.tag) not in {"item", "entry"}:
            continue
        fields = {}
        for node in entry:
            name = local(node.tag)
            value = "".join(node.itertext()).strip()
            if name == "link" and node.get("href") and node.get("rel", "alternate") == "alternate":
                value = node.get("href")
            if name == "author" and list(node):
                value = next((n.text for n in node if local(n.tag) == "name"), "")
            if name not in fields or name == "summary":
                fields[name] = value
        url = canonical_url(fields.get("link"), source)
        if not url:
            continue
        original_date = fields.get("pubDate") or fields.get("published") or fields.get("date")
        raw_excerpt = (
            fields.get("description")
            or fields.get("summary")
            or (fields.get("content") if source["publisher_id"] == "bls" else "")
            or ""
        )
        item = {
            "url": url,
            "external_id": fields.get("guid") or fields.get("id") or url,
            "title": plain(fields.get("title"))[:1000],
            "summary": plain(raw_excerpt)[:4000],
            "excerpt_origin": "feed",
            "author": plain(fields.get("creator") or fields.get("author")) or None,
            "published_at": utc(original_date),
            "published_at_original": original_date,
            "updated_at": utc(fields.get("updated")),
            "source_kind": source["source_kind"],
            "topics": source["topics"],
            "language": source.get("language", "en"),
            "rights_text": plain(fields.get("rights") or "") + " " + (fields.get("encoded") or raw_excerpt)[:150000],
        }
        if source["publisher_id"] == "nhc":
            storm = re.search(
                r"(?<![A-Z0-9])(AL|EP|CP)(\d{2})(20\d{2})(?![A-Z0-9])", item["title"] + " " + item["rights_text"], re.I
            )
            item.update(basin=source["basin"], storm_id=storm.group(0).upper() if storm else None)
            # Refresh URLs contain a changing bulletin timestamp; product and
            # official storm ID identify the revision chain across those URLs.
            product = re.search(r"/refresh/([^/]+)/", urlsplit(url).path)
            key = (item["storm_id"] + ":" + product[1] + ":" + urlsplit(url).query) if storm and product else url
            item["event_id"] = "nhc:" + key
        if item["title"]:
            items.append(item)
    if source["publisher_id"] == "nhc":
        # Summary and full advisory share a URL. Prefer the fuller feed excerpt.
        unique = {}
        for item in items:
            prior = unique.get(item["event_id"])
            if not prior or len(item["summary"]) > len(prior["summary"]):
                unique[item["event_id"]] = item
        return list(unique.values())
    return items


def parse_geojson(body, source):
    import json

    data = json.loads(body)
    if not isinstance(data.get("features"), list):
        raise ValueError("geojson-features-missing")
    items = []
    for feature in data["features"]:
        p = feature.get("properties") or {}
        if source["publisher_id"] == "usgs":
            item = {
                "external_id": feature["id"],
                "event_id": feature["id"],
                "title": p.get("title"),
                "url": p.get("url"),
                "published_at": utc(p.get("time")),
                "event_time": utc(p.get("time")),
                "updated_at": utc(p.get("updated")),
                "magnitude": p.get("mag"),
                "place": p.get("place"),
                "summary": f"Magnitude {p.get('mag')}; location: {p.get('place')}",
                "excerpt_origin": "structured",
                "source_kind": "observation",
                "topics": source["topics"],
            }
        else:
            item = {
                "external_id": p.get("id") or feature.get("id"),
                "event_id": p.get("id") or feature.get("id"),
                "title": p.get("headline") or p.get("event"),
                "url": p.get("@id") or feature.get("id"),
                "published_at": utc(p.get("sent")),
                "updated_at": utc(p.get("sent")),
                "event_time": utc(p.get("onset") or p.get("effective")),
                "expires_at": utc(p.get("expires")),
                "summary": plain(p.get("description"))[:4000],
                "excerpt_origin": "official-alert",
                "source_kind": "alert",
                "topics": source["topics"],
                "status": p.get("status"),
                "message_type": p.get("messageType"),
                "severity": p.get("severity"),
                "area": p.get("areaDesc"),
                "references": p.get("references"),
            }
        if canonical_url(item.get("url"), source):
            items.append(item)
    return items
