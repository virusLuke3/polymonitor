"""Official evidence adapters; dates, scope and amendment identities stay explicit."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from data_sources import source_value
from .normalizers import number, xml


def page(body):
    soup = BeautifulSoup(body, "html.parser")
    for element in soup(["script", "style", "nav", "footer"]):
        element.decompose()
    return soup, soup.get_text(" ", strip=True)


def date(value):
    value = value.strip()
    if not value:
        return None
    for pattern in ("%m/%d/%Y", "%d-%b-%y", "%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Unrecognized official date")


def nc_certification(body):
    soup, text = page(body)
    if "Finalizing 2026 Midterm Elections" not in text or "results on Election Day are unofficial" not in text:
        raise ValueError("NC certification notice identity changed")
    match = re.search(r"state canvass, scheduled for (\d+) a\.m\. (November \d+)", text)
    if not match:
        raise ValueError("NC state canvass schedule missing")
    schedule = date(match[2] + ", 2026")
    article = soup.find("meta", property="article:published_time")
    published = article.get("content") if article else None
    if not published and "November 4, 2026" in text:
        published = "2026-11-04"
    return {"items": [{"id": "US-NC:2026-11-03:state-canvass", "jurisdiction": "US-NC",
        "electionDate": "2026-11-03", "scope": "state-canvass-federal-contests",
        "status": "pending", "certifiedAt": None, "scheduledDate": schedule,
        "scheduledTime": f"{int(match[1]):02d}:00", "timeZone": "America/New_York",
        "evidencePublishedAt": published, "evidenceType": "official-pre-canvass-notice",
        "url": source_value("POLYMONITOR_POLITICS_NC_CERTIFICATION_URL")}],
        "coverage": "NC-2026-general-state-canvass", "recountsCoverage": "unavailable",
        "courtEventsCoverage": "unavailable"}


def dnc_roll_call(body):
    _, text = page(body)
    if "August 5, 2024" not in text or "Results of the electronic roll call" not in text:
        raise ValueError("DNC roll-call identity changed")
    count = re.search(r"([\d,]+) delegates from across the country cast their vote for Vice President Harris", text)
    if not count:
        raise ValueError("Official delegate vote count missing")
    return {"items": [{"id": "US:DEM:2024:virtual-roll-call", "year": 2024, "party": "DEM",
        "jurisdiction": "US", "eventDate": "2024-08-05", "historical": True,
        "basis": "convention-roll-call-votes", "candidate": "Kamala Harris",
        "delegates": int(count[1].replace(",", "")), "threshold": None,
        "thresholdStatus": "not-published-in-result", "unallocated": None,
        "delegateType": "pledged-and-automatic-participating", "stage": "roll-call-completed",
        "url": source_value("POLYMONITOR_POLITICS_DNC_ROLL_CALL_URL")}],
        "coverage": "2024-DNC-national-roll-call-result"}


def independent_expenditures(body):
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    required = {"cand_id", "cand_name", "spe_id", "spe_nam", "exp_amo", "sup_opp", "file_num",
                "amndt_ind", "tran_id", "prev_file_num", "receipt_dat", "exp_date", "dissem_dt"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("FEC independent-expenditure schema changed")
    transactions, filings, raw_count = {}, {}, 0
    for row in reader:
        raw_count += 1
        filing = row["file_num"].strip()
        previous = row["prev_file_num"].strip() or None
        if not filing.isdigit() or previous and not previous.isdigit() or not row["spe_id"]:
            raise ValueError("Missing FEC filing identity")
        if row["sup_opp"] not in ("S", "O", ""):
            raise ValueError("Unknown support/oppose code")
        key = ":".join((row["spe_id"], filing, row["tran_id"], row["cand_id"], row["sup_opp"]))
        item = {"id": key, "candidateId": row["cand_id"] or None, "candidate": row["cand_name"],
            "spenderId": row["spe_id"], "spender": row["spe_nam"], "filingId": filing,
            "transactionId": row["tran_id"], "previousFilingId": previous,
            "amendmentIndicator": row["amndt_ind"], "supportOppose": row["sup_opp"],
            "amount": number(row["exp_amo"]), "currency": "USD", "purpose": row.get("pur", ""),
            "payee": row.get("pay", ""), "expenditureDate": date(row["exp_date"]),
            "disseminationDate": date(row["dissem_dt"]), "receivedAt": date(row["receipt_dat"]),
            "electionType": row.get("ele_type"), "cycle": row.get("fec_election_yr")}
        if key in transactions and transactions[key] != item:
            raise ValueError("Conflicting FEC transaction identity")
        transactions[key] = item
        record = {"id": filing, "spenderId": row["spe_id"], "spender": row["spe_nam"],
                  "previousFilingId": previous, "amendmentIndicator": row["amndt_ind"],
                  "receivedAt": item["receivedAt"]}
        if filing in filings and filings[filing] != record:
            raise ValueError("Conflicting FEC filing identity")
        filings[filing] = record
    families = {}
    for filing in filings.values():
        current, seen = filing, set()
        while current["previousFilingId"]:
            if current["id"] in seen:
                raise ValueError("Cyclic FEC amendment chain")
            seen.add(current["id"])
            parent = filings.get(current["previousFilingId"])
            if parent is None:
                break
            if parent["spenderId"] != filing["spenderId"]:
                raise ValueError("FEC amendment crosses spender identity")
            current = parent
        root = current["previousFilingId"] or current["id"]
        families.setdefault((filing["spenderId"], root), []).append(filing)
    superseded = set()
    for family in families.values():
        # Multiple amendments can reference the same original. Keep only the latest
        # filing in that family; retaining both branches would duplicate notices.
        family.sort(key=lambda r: (r["receivedAt"] or "", int(r["id"])), reverse=True)
        superseded.update(r["id"] for r in family[1:])
    for filing in filings.values():
        filing["superseded"] = filing["id"] in superseded
        filing["predecessorAvailable"] = filing["previousFilingId"] in filings if filing["previousFilingId"] else None
    active = [r for r in transactions.values() if r["filingId"] not in superseded]
    current = [r for r in active if r["supportOppose"] in ("S", "O")]
    current.sort(key=lambda r: (r["receivedAt"] or "", int(r["filingId"]), r["id"]), reverse=True)
    revisions = sorted((r for r in filings.values() if r["previousFilingId"] or r["amendmentIndicator"].startswith("A")),
                       key=lambda r: (r["receivedAt"] or "", int(r["id"])), reverse=True)
    # The full original file remains in the evidence archive. Public projection is bounded;
    # no summed "total" conflates notices, amendments or a committee's periodic report.
    return {"items": current[:200], "availableCount": len(current), "rawCount": raw_count,
            "supersededTransactionCount": len(transactions) - len(active),
            "missingDirectionCount": len(active) - len(current),
            "rawMissingDirectionCount": sum(not r["supportOppose"] for r in transactions.values()),
            "partial": len(active) != len(current),
            "filingRevisions": revisions[:200], "filingRevisionCount": len(revisions),
            "filingCount": len(filings), "coverage": "24-and-48-hour-independent-expenditure-notices",
            "aggregation": "not-aggregated", "projectionLimit": 200}


def judicial_confirmations(body):
    soup, text = page(body)
    updated = re.search(r"Update as of (\d{2}/\d{2}/\d{4})", text)
    count = re.search(r"Total Confirmations:\s*(\d+)", text)
    table = next((t for t in soup.find_all("table") if "Confirmation Date" in t.get_text()), None)
    if not updated or not count or table is None:
        raise ValueError("Judicial confirmations table missing")
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        if len(cells) != 7:
            raise ValueError("Judicial confirmation columns changed")
        name, submitted, confirmed, court, incumbent, reason, vacancy = cells
        identity = "|".join((name, submitted, court))
        rows.append({"id": "uscourts:" + hashlib.sha256(identity.encode()).hexdigest()[:20],
            "name": name, "office": court, "submittedAt": date(submitted),
            "confirmedAt": date(confirmed), "stage": "confirmed", "nominationId": None,
            "incumbent": incumbent, "vote": None,
            "url": source_value("POLYMONITOR_POLITICS_JUDICIAL_CONFIRMATIONS_URL")})
    if len(rows) != int(count[1]) or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Judicial confirmations coverage mismatch")
    return {"items": sorted(rows, key=lambda r: r["confirmedAt"], reverse=True),
            "availableCount": len(rows), "publishedAt": date(updated[1]),
            "coverage": "USCourts-current-judicial-confirmation-list", "rollCallCoverage": "unavailable"}


def hearings_feed(body):
    root = xml(body)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Invalid GovInfo hearing feed")
    rows = []
    host = urlsplit(source_value("POLYMONITOR_POLITICS_HEARINGS_FEED_URL")).hostname
    for item in root.findall("channel/item"):
        identity, title = item.findtext("guid", ""), item.findtext("title", "")
        if not re.fullmatch(r"CHRG-\d+shrg\d+", identity) or not re.search("nominat", title, re.I):
            continue
        soup = BeautifulSoup(item.findtext("description", ""), "html.parser")
        links = [a.get("href", "") for a in soup.find_all("a")]
        url = next((u for u in links if urlsplit(u).path == f"/metadata/pkg/{identity}/mods.xml"), "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != host or parsed.username or parsed.query:
            raise ValueError("Unexpected hearing metadata URL")
        rows.append({"id": identity, "title": title, "publishedAt": item.findtext("pubDate"),
                     "url": item.findtext("link"), "metadataUrl": url})
    return {"items": rows, "availableCount": len(rows), "scannedCount": len(root.findall("channel/item")),
            "coverage": "recent-100-GovInfo-hearing-publications"}


def hearing_metadata(body):
    root = xml(body)
    ns = {"m": "http://www.loc.gov/mods/v3"}
    identity = root.findtext("m:recordInfo/m:recordIdentifier", namespaces=ns)
    dates = [date(d.text or "") for d in root.findall("m:extension/m:heldDate", ns)]
    title = root.findtext("m:titleInfo/m:title", namespaces=ns)
    if not re.fullmatch(r"CHRG-\d+shrg\d+", identity or "") or not dates or not re.search("nominat", title or "", re.I):
        raise ValueError("Hearing metadata identity or held date missing")
    return {"id": identity, "title": title, "heldDates": dates, "stage": "held",
            "committee": [n.text for n in root.findall("m:extension/m:congCommittee/m:name[@type='authority-standard']", ns)],
            "witnesses": [n.text for n in root.findall("m:extension/m:witness", ns)],
            "url": root.findtext("m:location/m:url[@displayLabel='Content Detail']", namespaces=ns),
            "congress": root.findtext("m:extension/m:congress", namespaces=ns),
            "publishedAt": root.findtext("m:extension/m:dateIngested", namespaces=ns),
            "nominationIds": [], "coverage": "official-published-hearing-record"}
