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


def jurisdictions(value):
    """Positive evidence only; an unrecognized jurisdiction never proves US CPI."""
    patterns = {
        "US": r"\bu\.?s\.?a?\b|united states|\bamerican\b|bureau of labor statistics|\bbls\b|federal reserve|\bfomc\b|\bfed\b",
        "EU": r"euro ?area|eurozone|european central|\becb\b|eurostat",
        "UK": r"\buk\b|united kingdom|british|bank of england|\bons\b",
        "CA": r"canad(?:a|ian)|bank of canada",
        "JP": r"japan(?:ese)?|bank of japan",
        "CN": r"china|chinese",
        "AU": r"australia(?:n)?|reserve bank of australia",
        "IN": r"\bindia(?:n)?\b",
    }
    return {code for code, pattern in patterns.items() if re.search(pattern, value)}


def market_coverage(market, sources, items):
    """Coverage declaration is separate from conservative article matching."""
    if items:
        return {"status": "available", "topic": None,
                "sourceIds": sorted({item["sourceId"] for item in items})}
    market = market or {}
    tags = market.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    category = text(str(market.get("category") or "") + " " + " ".join(map(str, tags)))
    question = text(market.get("title"))
    topic = "sports" if re.search(r"\bsports?\b|\bnfl\b|\bnba\b|football|soccer|basketball|baseball|tennis|esports", category) else (
        "crypto" if re.search(r"\bcrypto\b|bitcoin|ethereum", category + " " + question) else None)
    source_ids = [source["source_id"] for source in sources if source.get("enabled") and topic in source.get("topics", [])]
    return {"status": "unsupported" if topic and not source_ids else "unknown",
            "topic": topic, "sourceIds": source_ids}


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
    source_jurisdiction = {"bls": "US", "fed": "US", "ecb": "EU"}.get(item.get("publisher_id"))
    question_jurisdictions = jurisdictions(question)
    if source_jurisdiction and question_jurisdictions and question_jurisdictions != {source_jurisdiction}:
        return "unmatched", "Different or ambiguous statistical/monetary-policy jurisdiction."
    market_jurisdictions = question_jurisdictions or jurisdictions(context)
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
        if (source_jurisdiction and market_jurisdictions == {source_jurisdiction}
            and mm and im == mm and mc and ic == mc and md and id_ == md and my and iy == my):
            return "direct", "Same jurisdiction, official release indicator, reference month/year and headline/core plus year/month measurement basis."
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
        meeting_months = set(re.findall(r"\bin\s+(" + "|".join(MONTHS) + r")\b", question))
        if meeting_months and pm and MONTHS[int(pm) - 1] not in meeting_months:
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
