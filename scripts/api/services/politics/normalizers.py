"""Strict, source-specific adapters. Missing facts remain absent, never guessed."""
from __future__ import annotations

from data_sources import source_value

import csv
import hashlib
import html
import io
import json
import math
import re
import zipfile
from html.parser import HTMLParser
from collections import Counter
from datetime import datetime
from xml.etree import ElementTree as ET


def xml(body):
    if b"<!ENTITY" in body.upper() or b"<!DOCTYPE" in body.upper():
        raise ValueError("XML entity/doctype not allowed")
    return ET.fromstring(body)


def unzip(body, *, max_bytes=32 * 1024**2):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if len(members) != 1 or members[0].file_size > max_bytes:
            raise ValueError("Unexpected source archive")
        return z.read(members[0]).decode("utf-8-sig")


def number(value):
    if value is None or str(value).strip() == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite value")
    return result


def polls(body):
    raw = json.loads(body)
    if not isinstance(raw.get("polls"), list) or raw.get("meta", {}).get("count") != len(raw["polls"]):
        raise ValueError("Poll export count/schema mismatch")
    rows = []
    for p in raw["polls"]:
        if not p.get("raceId") or not p.get("date") or not isinstance(p.get("results"), dict):
            raise ValueError("Missing poll identity")
        values = [{"name": name, "value": number(value)} for name, value in p["results"].items()]
        if any(v["value"] is None or not 0 <= v["value"] <= 100 for v in values):
            raise ValueError("Invalid support percentage")
        rows.append({"id": hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:20],
                     "race": p["raceId"], "date": p["date"], "pollster": p.get("pollster"),
                     "sample": p.get("sampleSize"), "population": p.get("population"),
                     "marginOfError": p.get("marginOfError"), "results": values,
                     "url": p.get("sourceUrl"), "method": None, "publishedAt": None})
    return {"items": sorted(rows, key=lambda r: r["date"], reverse=True),
            "availableCount": len(rows), "attribution": 'Decision Labs (decisionlabs.ai) · CC BY 4.0',
            "exportGeneratedAt": raw["meta"].get("generatedAt")}


def early_vote(body):
    rows = list(csv.DictReader(io.StringIO(unzip(body))))
    fields = {"sent": "abs_sent", "accepted": "abs_accepted", "spoiled": "abs_spoiled_EV",
              "receivedNotCounted": "abs_received_not_counted", "outstanding": "abs_outstanding"}
    if not rows or not set(fields.values()).issubset(rows[0]):
        raise ValueError("Absentee columns changed")
    result = []
    for r in rows:
        result.append({"id": r["county_name"], "date": datetime.strptime(r["election_date"], "%m/%d/%Y").date().isoformat(),
                       **{k: int(r[v]) for k, v in fields.items()}})
    if len({r["id"] for r in result}) != len(result) or len({r["date"] for r in result}) != 1:
        raise ValueError("Duplicate county or mixed election")
    return {"items": result, "totals": {k: sum(r[k] for r in result) for k in fields},
            "electionDate": result[0]["date"], "jurisdiction": "US-NC", "expectedCounties": 100}


def nc_results(body):
    races, seen = {}, set()
    # NCSBE represents an absent party with a NUL field; preserve it as empty.
    text = unzip(body)
    if any("\x00" in field and field != "\x00" for line in text.splitlines() for field in line.split("\t")):
        raise ValueError("Unexpected embedded NUL in results")
    for row in csv.DictReader(io.StringIO(text.replace("\x00", "")), delimiter="\t"):
        if not row.get("Contest Name", "").startswith(("US SENATE", "US HOUSE")):
            continue
        # Group ID and date are source identities, not fuzzy candidate-name matches.
        identity = row["Election Date"] + ":" + row["Contest Group ID"]
        unique = (identity, row["County"], row["Precinct"], row["Choice"])
        if unique in seen:
            raise ValueError("Duplicate precinct result")
        seen.add(unique)
        race = races.setdefault(identity, {"id": identity, "title": row["Contest Name"],
            "electionDate": datetime.strptime(row["Election Date"], "%m/%d/%Y").date().isoformat(), "choices": {}, "counties": set()})
        race["counties"].add(row["County"])
        choice = race["choices"].setdefault(row["Choice"], {"name": row["Choice"], "party": row["Choice Party"].strip(), "votes": 0})
        choice["votes"] += int(row["Total Votes"])
    items = [{**r, "choices": sorted(r["choices"].values(), key=lambda c: c["votes"], reverse=True),
              "counties": len(r["counties"]), "certified": None, "remainingVotes": None} for r in races.values()]
    if not items:
        raise ValueError("No federal contests in NC file")
    return {"items": items, "jurisdiction": "US-NC", "basis": "published-precinct-tabulation"}


def finance(body):
    rows = []
    for values in csv.reader(io.StringIO(unzip(body)), delimiter="|"):
        if len(values) != 30 or not re.fullmatch(r"[HSP][A-Z0-9]{8}", values[0]):
            raise ValueError("FEC weball schema/identity changed")
        rows.append({"id": values[0], "name": values[1], "party": values[4], "state": values[18],
                     "district": values[19], "office": values[0][0],
                     "receipts": number(values[5]), "spending": number(values[7]),
                     "transfersIn": number(values[6]), "transfersOut": number(values[8]),
                     "cash": number(values[10]), "debt": number(values[16]),
                     "periodEnd": datetime.strptime(values[27], "%m/%d/%Y").date().isoformat() if values[27] else None,
                     "url": source_value('POLYMONITOR_URL_WWW_FEC_GOV_DATA_CANDIDATE_507A0C') + values[0] + "/"})
    if not rows:
        raise ValueError("Empty FEC summary")
    return {"items": sorted(rows, key=lambda r: r["receipts"] or 0, reverse=True), "availableCount": len(rows)}


def house(body):
    root = xml(body)
    if root.tag != "MemberData" or not root.findtext("title-info/congress-num"):
        raise ValueError("House roster schema changed")
    seats = []
    states = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
    for member in root.findall("members/member"):
        district = member.findtext("statedistrict", "")
        if district[:2] not in states:
            continue
        info = member.find("member-info")
        if info is None or not district:
            raise ValueError("Missing House identity")
        seats.append({"id": district, "name": info.findtext("official-name") or info.findtext("namelist"),
                      "party": info.findtext("party") or "Vacant", "caucus": info.findtext("caucus"),
                      "bioguide": info.findtext("bioguideID"), "sworn": info.findtext("sworn-date"),
                      "url": source_value('POLYMONITOR_URL_CLERK_HOUSE_GOV_MEMBERS_2DAD42') + (info.findtext("bioguideID") or "")})
    if not 400 <= len(seats) <= 435 or len({r["id"] for r in seats}) != len(seats):
        raise ValueError("Unexpected House seat coverage")
    return {"items": seats, "counts": dict(Counter(s["party"] for s in seats)),
            "congress": root.findtext("title-info/congress-num"), "publishedAt": root.get("publish-date"),
            "majority": root.findtext("title-info/majority"), "totalSeats": 435,
            "basis": "current-membership", "url": source_value('POLYMONITOR_URL_CLERK_HOUSE_GOV_MEMBERS_552C04')}


def bill_feed(body, congress):
    root = xml(body)
    if root.tag != "rss":
        raise ValueError("Not a bill feed")
    rows = {}
    for item in root.findall("channel/item"):
        identity = item.findtext("guid", "")
        match = re.fullmatch(r"BILLS-(\d+)(hr|s|hjres|sjres|hconres|sconres|hres|sres)(\d+)([a-z]+)", identity)
        if not match or int(match[1]) != congress:
            continue
        key = f"{match[1]}{match[2]}{match[3]}"
        title = " ".join(html.unescape(item.findtext("title", "")).split())
        rows[key] = {"id": key, "congress": congress, "type": match[2], "number": match[3],
                     "title": title, "version": match[4], "publishedAt": item.findtext("pubDate"),
                     "url": item.findtext("link"), "statusUrl": f"{source_value('POLYMONITOR_URL_WWW_GOVINFO_GOV_BULKDATA_BILLSTATUS_D7E568')}{congress}/{match[2]}/BILLSTATUS-{key}.xml"}
    return {"items": list(rows.values()), "availableCount": len(rows), "coverage": "recent-publications"}


def bill_status(body):
    b = xml(body).find("bill")
    if b is None or not b.findtext("congress") or not b.findtext("number"):
        raise ValueError("Missing bill identity")
    identity = b.findtext("congress") + b.findtext("type").lower() + b.findtext("number")
    actions = [{"date": a.findtext("actionDate"), "text": a.findtext("text"), "type": a.findtext("type"),
                "code": a.findtext("actionCode"), "votes": [v.findtext("url") for v in a.findall("recordedVotes/recordedVote") if v.findtext("url")]} for a in b.findall("actions/item")]
    return {"id": identity, "title": b.findtext("title"), "updatedAt": b.findtext("updateDate"),
            "introducedAt": b.findtext("introducedDate"), "url": b.findtext("legislationUrl"),
            "latestAction": {"date": b.findtext("latestAction/actionDate"), "text": b.findtext("latestAction/text")},
            "actions": actions[:60], "actionCount": len(actions),
            "committees": [a.findtext("name") for a in b.findall("committees/item")],
            "cosponsors": len(b.findall("cosponsors/item")),
            "textVersions": [{"name": a.findtext("type"), "date": a.findtext("date"),
                              "urls": [f.findtext("url") for f in a.findall("formats/item")]} for a in b.findall("textVersions/item")][:20],
            "laws": [{"type": a.findtext("type"), "number": a.findtext("number")} for a in b.findall("laws/item")]}


def announcements(body):
    root = xml(body)
    if root.tag != "rss":
        raise ValueError("Not a presidential announcement feed")
    rows = []
    for item in root.findall("channel/item"):
        title = html.unescape(item.findtext("title", ""))
        if not re.search(r"nominat|appoint", title, re.I):
            continue
        url = item.findtext("link")
        text = plain_text(item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", ""))
        start = re.search(r"NOMINATIONS? (?:SENT TO THE SENATE|AND WITHDRAWALS)", text, re.I)
        excerpt = text[start.start():] if start else ""
        rows.append({"id": item.findtext("guid") or url, "title": title, "url": url,
                     "publishedAt": item.findtext("pubDate"), "stage": "announcement", "text": excerpt[:16000]})
    return {"items": rows, "coverage": "recent-presidential-announcements"}


def plain_text(markup):
    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)
    parser = Text()
    parser.feed(markup)
    return " ".join(" ".join(parser.parts).split())


def funding_law(body):
    """Pinned, verified law adapter; an original law is not a current-law search."""
    text = plain_text(body.decode("utf-8"))
    if "Public Law 119-103" not in text or "fiscal year 2027" not in text:
        raise ValueError("Funding law identity changed")
    match = re.search(r"Sec\. 106\.(.*?)Sec\. 107\.", text)
    coverage = re.search(r"Sec\. 101\.(.*?)Sec\. 102\.", text)
    if not match or not coverage:
        raise ValueError("Funding provision unavailable")
    expiration = re.search(r"Expiration date\.>>\s*([A-Za-z]+ \d{1,2}, \d{4})", match[1])
    if not expiration:
        raise ValueError("Explicit expiration date unavailable")
    date = datetime.strptime(expiration[1], "%B %d, %Y").date().isoformat()
    clauses = re.findall(r"\((\d+)\)\s+(The .*?)(?=\(\d+\) The |$)", coverage[1])
    if [int(i) for i, _ in clauses] != list(range(1, 13)):
        raise ValueError("Appropriations scope changed")
    return {"id": "PLAW-119publ103", "billId": "119hr6500", "fiscalYear": 2027,
            "expirationDate": date, "expirationTime": None, "currentCoverageVerified": False,
            "expirationClause": match[1].strip(), "coverage": [{"id": i, "text": t.strip()} for i, t in clauses],
            "url": source_value('POLYMONITOR_URL_WWW_GOVINFO_GOV_CONTENT_PKG_PLAW_119PUBL103_HTML_PLAW_119PUBL103_HTM_9E9799')}
