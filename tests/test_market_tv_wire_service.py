from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from api.services import live_video_source_service as service
from api.services import youtube_live_probe_service as youtube_probe


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


def test_market_tv_wire_category_filter_runs_before_limit() -> None:
    payload = {
        "generatedAt": "2026-06-15T00:00:00Z",
        "status": "ok",
        "cacheMode": "seeded",
        "items": [
            {"id": "yt-macro", "displayName": "YouTube Macro", "category": "macro", "sourceType": "youtube", "status": "ready", "relevanceScore": 101},
            {"id": "macro-1", "displayName": "Macro 1", "category": "macro", "sourceType": "hls", "status": "ready", "relevanceScore": 100},
            {"id": "macro-2", "displayName": "Macro 2", "category": "macro", "sourceType": "hls", "status": "ready", "relevanceScore": 99},
            {"id": "sports-1", "displayName": "Sports 1", "category": "sports", "sourceType": "hls", "status": "ready", "relevanceScore": 80},
            {"id": "sports-2", "displayName": "Sports 2", "category": "sports", "sourceType": "hls", "status": "ready", "relevanceScore": 79},
        ],
    }

    top_payload = service.normalize_market_tv_wire_payload(payload, limit=2)
    sports_payload = service.normalize_market_tv_wire_payload(payload, limit=2, category="sports")

    assert [item["id"] for item in top_payload["items"]] == ["macro-1", "macro-2"]
    assert all(item["sourceType"] == "hls" for item in top_payload["items"])
    assert [item["id"] for item in sports_payload["items"]] == ["sports-1", "sports-2"]
    assert sports_payload["selection"] == {
        "category": "sports",
        "total": 2,
        "returned": 2,
        "limit": 2,
        "truncated": False,
    }


def test_youtube_probe_parses_live_video_and_hls_manifest() -> None:
    html = r'''
<html><head><meta property="og:url" content="https://www.youtube.com/@Foxweather/live"></head>
<script>
{"channelId":"UCabc123","ownerChannelName":"FOX Weather","videoDetails":{"videoId":"abcDEF12345","title":"FOX Weather Live","isLive":true},"hlsManifestUrl":"https:\/\/example.com\/live.m3u8\u0026sig=1"}
</script>
</html>
'''

    payload = youtube_probe.parse_channel_html(html)

    assert payload["channelExists"] is True
    assert payload["channelId"] == "UCabc123"
    assert payload["channelName"] == "FOX Weather"
    assert payload["videoId"] == "abcDEF12345"
    assert payload["isLive"] is True
    assert payload["title"] == "FOX Weather Live"
    assert payload["hlsUrl"] == "https://example.com/live.m3u8&sig=1"


def test_market_tv_wire_enriches_youtube_manifest_sources() -> None:
    def probe(channel: str, video_id: str) -> dict:
        if channel == "@Foxweather":
            return {
                "videoId": "abcDEF12345",
                "isLive": True,
                "channelExists": True,
                "channelId": "UCabc123",
                "channelName": "FOX Weather",
                "hlsUrl": "https://example.com/fox-weather.m3u8",
                "title": "FOX Weather Live Now",
                "error": "",
            }
        return {
            "videoId": "",
            "isLive": False,
            "channelExists": True,
            "channelName": "",
            "hlsUrl": "",
            "title": "",
            "error": "",
        }

    payload = service.build_market_tv_wire_payload(
        {"utc_now_iso": lambda: "2026-06-15T00:00:00Z", "youtube_live_probe": probe},
        include_iptv=False,
    )
    fox_weather = next(item for item in payload["items"] if item["id"] == "fox-weather-live")

    assert payload["sources"]["youtubeLiveProbe"]["liveCount"] >= 1
    assert fox_weather["youtubeProbeStatus"] == "live"
    assert fox_weather["youtubeChannelId"] == "UCabc123"
    assert fox_weather["youtubeLiveVideoId"] == "abcDEF12345"
    assert fox_weather["youtubeHlsUrl"] == "https://example.com/fox-weather.m3u8"
    assert "youtube-nocookie.com/embed/abcDEF12345" in fox_weather["youtubeEmbedUrl"]
    assert fox_weather["fallbackVideoId"] == "abcDEF12345"
    assert fox_weather["externalUrl"] == "https://www.youtube.com/watch?v=abcDEF12345"


def test_market_youtube_channels_payload_filters_curated_youtube_sources() -> None:
    payload = {
        "generatedAt": "2026-06-15T00:00:00Z",
        "status": "ok",
        "cacheMode": "seeded",
        "items": [
            {
                "id": "yt-weather",
                "displayName": "Weather Live",
                "category": "weather",
                "sourceType": "youtube",
                "youtubeProbeStatus": "live",
                "youtubeLiveVideoId": "abcDEF12345",
                "youtubeEmbedUrl": "https://www.youtube-nocookie.com/embed/abcDEF12345",
                "status": "ready",
                "relevanceScore": 95,
            },
            {
                "id": "hls-weather",
                "displayName": "HLS Weather",
                "category": "weather",
                "sourceType": "hls",
                "hlsUrl": "https://example.com/live.m3u8",
                "status": "ready",
                "relevanceScore": 99,
            },
            {
                "id": "yt-geo",
                "displayName": "Geo Live",
                "category": "geo",
                "sourceType": "youtube",
                "fallbackVideoId": "defGHI12345",
                "status": "ready",
                "relevanceScore": 90,
            },
        ],
    }

    all_payload = service.normalize_market_youtube_channels_payload(payload, limit=10)
    weather_payload = service.normalize_market_youtube_channels_payload(payload, limit=10, category="weather")

    assert [item["id"] for item in all_payload["items"]] == ["yt-weather", "yt-geo"]
    assert [item["id"] for item in weather_payload["items"]] == ["yt-weather"]
    assert all_payload["summary"]["total"] == 2
    assert all_payload["summary"]["embedReady"] == 2
    assert "youtube-nocookie.com/embed/defGHI12345" in all_payload["items"][1]["youtubeEmbedUrl"]


def test_market_tv_wire_seed_keeps_curated_manifest_items_when_iptv_is_large(monkeypatch) -> None:
    def load_manifest() -> list[dict]:
        return [
            {
                "id": "yt-low-score",
                "displayName": "Low Score YouTube",
                "category": "culture",
                "sourceType": "youtube",
                "youtubeHandle": "@demo",
                "youtubeChannelId": "UCdemo",
                "externalUrl": "https://www.youtube.com/@demo/streams",
                "sourceUrl": "https://www.youtube.com/@demo/streams",
                "marketTags": ["culture"],
            }
        ]

    playlist = "#EXTM3U\n" + "\n".join(
        f'#EXTINF:-1 tvg-id="Demo{i}",Demo {i}\nhttps://example.com/live/{i}.m3u8'
        for i in range(32)
    )

    monkeypatch.setattr(service, "load_manifest_items", load_manifest)
    monkeypatch.setenv("POLYDATA_MARKET_TV_WIRE_SEED_LIMIT", "24")

    payload = service.build_market_tv_wire_payload(
        {
            "utc_now_iso": lambda: "2026-06-15T00:00:00Z",
            "http_text_get": lambda url, **kwargs: playlist,
            "market_tv_youtube_probe_enabled": False,
        }
    )

    ids = [item["id"] for item in payload["items"]]

    assert "yt-low-score" in ids
    assert len(payload["items"]) == 24
