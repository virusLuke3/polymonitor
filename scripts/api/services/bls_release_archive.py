"""Original BLS documents owned by the content worker; calendars only read them."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
TITLES = {"cpi": "Consumer Price Index", "ppi": "Producer Price Indexes", "nfp": "Employment Situation"}


def archive_root(snapshot_store):
    return Path(snapshot_store.db_path).parent / "bls-release-archive"


def read_latest(snapshot_store, kind):
    if snapshot_store is None or not getattr(snapshot_store, "db_path", None):
        return {}
    try:
        value = json.loads((archive_root(snapshot_store) / kind / "latest.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def extract_text(pdf, *, timeout=8):
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("bls-archive-not-pdf")
    with tempfile.TemporaryDirectory(prefix="polymonitor-bls-pdf-") as directory:
        path = Path(directory) / "release.pdf"
        path.write_bytes(pdf)
        output = Path(directory) / "release.txt"
        subprocess.run(["pdftotext", "-layout", str(path), str(output)], check=True,
                       timeout=max(.1, min(8, timeout)), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if output.stat().st_size > 2_500_000:
            raise ValueError("bls-archive-text-too-large")
        return output.read_text()


def _release_time(date, clock):
    value = re.sub(r"\s+", " ", date).strip() + " " + clock.replace(".", "").upper()
    return datetime.strptime(value, "%B %d, %Y %I:%M %p").replace(tzinfo=EASTERN).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_release(text, kind):
    flat = re.sub(r"\s+", " ", text)
    label = {"cpi": r"CONSUMER PRICE INDEX", "ppi": r"PRODUCER PRICE INDEXES", "nfp": r"(?:THE )?EMPLOYMENT SITUATION"}[kind]
    period = re.search(label + r"\s*[–—-]\s*" + MONTH + r"\s+(20\d{2})", flat, re.I)
    header = re.search(r"(\d{1,2}:\d{2}\s+[ap]\.m\.)\s*\(ET\)\s+\w+,\s*(" + MONTH + r"\s+\d{1,2},\s+20\d{2})", flat[:700], re.I)
    number = re.search(r"USDL[\s-]*(\d{2}-\d{4})", flat[:700])
    if not period or not header or not number or "Bureau of Labor Statistics" not in flat[:3000]:
        raise ValueError("bls-archive-release-identity-missing")
    reference = f"{period[1].title()} {period[2]}"
    result = {"kind": kind, "referencePeriod": reference, "releaseNumber": "USDL-" + number[1],
              "published_at": _release_time(header[2], header[1]),
              "title": f"{TITLES[kind]} — {reference}",
              "summary": flat[period.end():period.end() + 1600].strip()}
    upcoming = re.search(r"(?:Consumer Price Index|Producer Price Index|Employment Situation)(?: news release)? for "
                         + MONTH + r"\s+(20\d{2})\s+is scheduled to be published on\s+\w+,\s*("
                         + MONTH + r"\s+\d{1,2},\s+20\d{2}),\s+at\s+(\d{1,2}:\d{2}\s+[ap]\.m\.)\s*\(ET\)", flat, re.I)
    if upcoming:
        result["next_release"] = {"referencePeriod": f"{upcoming[1].title()} {upcoming[2]}",
                                  "releaseAt": _release_time(upcoming[3], upcoming[5])}
    return result


def atomic_write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_document(snapshot_store, kind, pdf, text, metadata):
    directory = archive_root(snapshot_store) / kind
    digest = hashlib.sha256(pdf).hexdigest()
    stem = directory / digest
    manifest = stem.with_suffix(".json")
    if manifest.exists():
        # Preserve the first receipt of this version across retries/restarts.
        saved = json.loads(manifest.read_text())
    else:
        saved = {**metadata, "sha256": digest, "bytes": len(pdf), "pdfFile": digest + ".pdf",
                 "textFile": digest + ".txt"}
    atomic_write(stem.with_suffix(".pdf"), pdf)
    atomic_write(stem.with_suffix(".txt"), text.encode())
    atomic_write(manifest, json.dumps(saved, ensure_ascii=False, indent=2).encode())
    latest = {**saved, "pdfHttp": metadata.get("pdfHttp", {})}
    atomic_write(directory / "latest.json", json.dumps(latest, ensure_ascii=False, indent=2).encode())
    return latest
