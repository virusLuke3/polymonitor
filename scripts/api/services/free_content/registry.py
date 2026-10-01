from __future__ import annotations
import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[3] / "runtime" / "free_news_sources.json"


def sources():
    return json.loads(REGISTRY_PATH.read_text())["sources"]


def source_map():
    return {source["source_id"]: source for source in sources()}
