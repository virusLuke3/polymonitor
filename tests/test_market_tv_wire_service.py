from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from api.services import live_video_source_service as service


def test_market_tv_wire_manifest_payload_builds_without_network() -> None:
    payload = service.build_market_tv_wire_payload({"utc_now_iso": lambda: "2026-06-15T00:00:00Z"}, include_iptv=False)

    assert payload["status"] == "ok"
    assert payload["summary"]["total"] >= 10
    assert payload["items"]
    assert payload["items"][0]["relevanceScore"] >= payload["items"][-1]["relevanceScore"]
    assert {category["id"] for category in payload["categories"]} >= {"macro", "geo", "weather"}


def test_market_tv_wire_m3u_parser_keeps_https_hls_and_marks_not_24_7() -> None:
    text = """
#EXTM3U
#EXTINF:-1 tvg-id="Demo.News" tvg-country="US" tvg-language="en",Demo News [Not 24/7]
https://example.com/live/demo.m3u8
#EXTINF:-1 tvg-id="Bad.Http",Bad HTTP
http://example.com/live/bad.m3u8
"""
    items = service.parse_m3u_playlist(text, category="news", source_url="https://iptv.example/news.m3u", generated_at="2026-06-15T00:00:00Z")

    assert len(items) == 1
    assert items[0]["displayName"] == "Demo News"
    assert items[0]["sourceType"] == "hls"
    assert items[0]["status"] == "not_24_7"
    assert items[0]["country"] == "US"


def test_market_tv_wire_runtime_snapshot_does_not_live_build_by_default() -> None:
    payload = service.get_market_tv_wire_snapshot({"utc_now_iso": lambda: "2026-06-15T00:00:00Z"}, limit=5)

    assert payload["status"] == "warming"
    assert payload["cacheMode"] == "warming"
    assert payload["items"] == []
