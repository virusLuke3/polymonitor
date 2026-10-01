"""Conservative, deterministic relations. A direct relation never means YES or settlement."""

from __future__ import annotations
import json
import re
from datetime import datetime, timezone

MONTHS = "january february march april may june july august september october november december".split()
BROAD = set(
    "will would could should above below over under before after more less than this that their have from with into when what how who the and for not yes win winner price prices increase decrease change total market markets weather economy economic inflation official news release update published report statement policy federal reserve board nasa company spacex launch launches launched month year million billion percent rate rates".split()
)


def text(value):
    return re.sub(r"\s+", " ", str(value or "").lower())


def years(value):
    return set(re.findall(r"\b20\d{2}\b", value))


def months(value):
    return set(re.findall(r"\b(?:" + "|".join(MONTHS) + r")\b", value))


def tokens(value):
    return {s for s in re.findall(r"[a-z][a-z0-9-]{3,}", value) if s not in BROAD and s not in MONTHS}


def metric(value):
    family = (
        "cpi"
        if re.search(r"\bcpi\b|consumer price", value)
        else "ppi"
        if re.search(r"\bppi\b|producer price", value)
        else "employment"
        if re.search(r"payroll|unemployment|employment situation", value)
        else None
    )
    core = (
        "core"
        if re.search(r"\bcore\b|excluding food and energy|less food and energy", value)
        else "headline"
        if "all items" in value or "headline" in value
        else None
    )
    cadence = (
        "yoy"
        if re.search(r"year.over.year|year.on.year|12.month|annual|\byoy\b", value)
        else "mom"
        if re.search(r"month.over.month|month.on.month|\bmom\b", value)
        else None
    )
    return family, core, cadence


def relate(market, item):
    tags = market.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    question = text(market.get("title"))
    context = text(" ".join(str(market.get(k) or "") for k in ("title", "description", "rules")) + " " + " ".join(tags))
    article = text(item.get("title"))
    body = text(article + " " + str(item.get("summary") or ""))
    if item.get("publisher_id") in {"bls", "fed"} and re.search(
        r"euro ?area|eurozone|european central|\becb\b|\buk\b|united kingdom|\bchina\b", question
    ):
        return "unmatched", "Different statistical or monetary-policy jurisdiction."
    if item.get("publisher_id") == "ecb" and re.search(
        r"\bfed\b|fomc|federal reserve|\bu\.s\.|united states|\buk\b|united kingdom|\bchina\b", question
    ):
        return "unmatched", "Different monetary-policy jurisdiction."
    my, iy = years(question), years(article)
    if not iy and item.get("published_at"):
        iy = {item["published_at"][:4]}
    if my and iy and not my.intersection(iy):
        return "unmatched", "Different event years."
    mm, im = months(question), months(article)
    if mm and im and not mm.intersection(im):
        return "unmatched", "Different reference months."
    mf, mc, md = metric(question)
    inf, ic, id_ = metric(article)
    if mf and inf and mf != inf:
        return "unmatched", "Different statistical indicators."
    if mf and inf and ((mc and ic and mc != ic) or (md and id_ and md != id_)):
        return "unmatched", "Different headline/core or year/month measurement basis."
    if mf and mf in item.get("topics", []):
        if mm and not im:
            return (
                "context",
                "Same statistical release family; reference month or measurement basis is not fully established.",
            )
        if mm and im and mc and ic == mc and md and id_ == md and my and my.intersection(iy):
            return "direct", "Same indicator, reference month/year and headline/core plus year/month measurement basis."
        return (
            "context",
            "Same statistical release family; this excerpt does not establish every contract measurement condition.",
        )
    if item.get("storm_id"):
        ids = set(re.findall(r"\b(?:al|ep|cp)\d{2}20\d{2}\b", context, re.I))
        if ids and item["storm_id"].lower() not in {i.lower() for i in ids}:
            return "unmatched", "Different storm identifiers."
        basins = {"atlantic": r"atlantic", "eastern-pacific": r"eastern pacific|east pacific|eastern north pacific"}
        if ids and re.search(basins.get(item.get("basin"), r"(?!)"), context) and my.intersection(iy):
            return (
                "context",
                "Same storm identifier, year and basin; the market observation window is not fully established.",
            )
    # Broad publisher, category or company alone is never enough.
    common = tokens(question).intersection(tokens(article))
    if re.search(r"\bfed\b|federal reserve|fomc", question) and item.get("publisher_id") == "fed":
        if "monetary" not in item["url"] and "fomc" not in body:
            return "unmatched", "Different Federal Reserve event."
        pm = item.get("published_at", "")[5:7]
        if mm and pm and MONTHS[int(pm) - 1] not in mm:
            return "unmatched", "Different policy announcement month."
        return (
            "context",
            "Federal Reserve monetary-policy announcement; the exact meeting and contract conditions need verification.",
        )
    if len(common) < 2:
        return "unmatched", "No specific shared event or entity evidence."
    if item["source_kind"] in {"alert", "observation"}:
        places = tokens(item.get("area") or item.get("place"))
        if not tokens(question).intersection(places):
            return "unmatched", "No matched location evidence."
        return "context", "Shared event/location terms: " + ", ".join(
            sorted(common)
        ) + ". Exact geographic and observation-window overlap is not established."
    return "context", "Shared specific terms: " + ", ".join(
        sorted(common)
    ) + ". Time, event and contract conditions are not fully established."
