"""Same-channel playback candidates; the TV watcher owns live-ID resolution."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

STATE_NAMESPACE = "state:content:tv-live"
LIVE_REFRESH_SECONDS = 6 * 3600
FAILED_REFRESH_SECONDS = 900
LAST_GOOD_SECONDS = 36 * 3600
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Reviewed broadcaster identities, not matches inferred from similar names.
# Order follows WorldMonitor 65860c21; existing HLS URLs stay with their owner.
CHANNELS = {
    "trusted-hls-bloomberg": ("UCIALMKvObZNtJ6AmdCLP7Lg", "QB5BNdBFujE", False, ("bloomberg-tv", "bloomberg-markets-youtube")),
    "trusted-hls-sky-news": ("", "xDWQ3LkccY8", False, ("sky-news-live",)),
    "trusted-hls-euronews": ("", "pykpO5kQJ98", True, ("euronews-live", "trusted-youtube-euronews")),
    "trusted-hls-dw": ("UCknLrEdhRCp1aegoMqRaCZg", "LuKwFajn37U", False, ("dw-news-live",)),
    "trusted-hls-france24": ("", "HvZt-nh9sGg", False, ("france24-english-youtube",)),
    "trusted-hls-aljazeera": ("UCNye-wNBqNL5ZzHSJj3l8Bg", "gCNeDWCI0vo", False, ("aljazeera-live",)),
    "trusted-hls-alarabiya": ("", "n7eQejkXbnM", False, ("trusted-youtube-alarabiya",)),
    "trusted-hls-abc-news": ("UCBi2mrWuNuyYy4gbM6fU18Q", "", True, ("abc-news-live", "abc-news-youtube")),
    "trusted-hls-nbc-news": ("UCeY0bbntWzzVIaj2z3QigXg", "", True, ("nbc-news-youtube", "trusted-youtube-nbc-news")),
}


def parse_current_live(html: str, channel_id: str, video_id: str = "") -> dict[str, Any]:
    """A completed live recording or RSS upload is not a current broadcast."""
    player = None
    for match in re.finditer(r"(?:ytInitialPlayerResponse\s*=|\"playerResponse\"\s*:)\s*", html):
        try:
            player, _ = json.JSONDecoder().raw_decode(html[match.end():])
            if isinstance(player, dict):
                break
        except (ValueError, TypeError):
            continue
    if not isinstance(player, dict):
        return {"status": "error", "error": "player response unavailable"}
    details = player.get("videoDetails") or {}
    if (channel_id and details.get("channelId") != channel_id) or (video_id and details.get("videoId") != video_id):
        return {"status": "error", "error": "channel identity mismatch or unavailable"}
    availability = player.get("playabilityStatus") or {}
    if availability.get("status") not in {None, "OK"} or availability.get("playableInEmbed") is False:
        return {"status": "not-live", "error": "broadcast unavailable or embedding disabled"}
    broadcast = (player.get("microformat") or {}).get("playerMicroformatRenderer", {}).get("liveBroadcastDetails", {})
    live = details.get("isLive") is True or broadcast.get("isLiveNow") is True
    video_id = str(details.get("videoId") or "")
    if not live or broadcast.get("endTimestamp") or details.get("isUpcoming"):
        return {"status": "not-live"}
    if not VIDEO_ID.fullmatch(video_id):
        return {"status": "error", "error": "invalid video identity"}
    return {"status": "live", "videoId": video_id, "channelId": details.get("channelId") or channel_id}


def refresh_live_channels(dependencies: Any) -> dict[str, Any]:
    store = dependencies.snapshot_store
    fetch = dependencies.http_text_get
    if store is None or fetch is None:
        return {}
    channels = sorted({spec[0] for spec in CHANNELS.values() if spec[0]})
    # Fixed broadcasts get a daily current-live audit; do not discover a different
    # featured broadcast and silently change the intended station/program.
    channels += sorted({"video:" + spec[1] for spec in CHANNELS.values() if spec[1]})

    def resolve(channel: str) -> tuple[str, dict[str, Any]]:
        now = time.time()
        old = store.get_stale(STATE_NAMESPACE, channel) or {}
        if old.get("nextAttemptAt", 0) > now:
            return channel, old
        try:
            pinned = channel.removeprefix("video:") if channel.startswith("video:") else ""
            url = f"https://www.youtube.com/watch?v={pinned}" if pinned else f"https://www.youtube.com/channel/{channel}/live"
            html = fetch(url, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.8"})
            result = parse_current_live(html, "" if pinned else channel, pinned)
        except Exception as exc:
            result = {"status": "error", "error": type(exc).__name__}
        result["lastAttemptAt"] = now
        refresh_seconds = 86400 if channel.startswith("video:") else LIVE_REFRESH_SECONDS
        result["nextAttemptAt"] = now + (FAILED_REFRESH_SECONDS if result["status"] == "error" else refresh_seconds)
        if result["status"] == "live":
            result["resolvedAt"] = now
        elif result["status"] == "error" and now - old.get("resolvedAt", 0) <= LAST_GOOD_SECONDS:
            for key in ("videoId", "resolvedAt", "channelId"):
                if key in old:
                    result[key] = old[key]
        store.set(STATE_NAMESPACE, channel, result, LAST_GOOD_SECONDS)
        return channel, result

    with ThreadPoolExecutor(max_workers=4) as executor:
        return dict(executor.map(resolve, channels))


def attach_playback_sources(items: list[dict[str, Any]], resolved: dict[str, Any]) -> None:
    now = time.time()
    for item in items:
        if item.get("sourceType") != "hls":
            continue
        channel, pinned, youtube_first, _ = CHANNELS.get(item.get("id"), ("", item.get("fallbackVideoId") or "", False, ()))
        hls = {"kind": "hls", "url": item.get("hlsUrl"), "proxy": bool(item.get("hlsProxyRequired")),
               "proxyFallback": item.get("playbackTier") == "trusted-hls"}
        videos: list[dict[str, Any]] = []
        info = resolved.get(channel) or {}
        # Keep the last success's own time; a failed refresh never renews it.
        if info.get("videoId") and now - info.get("resolvedAt", 0) <= LAST_GOOD_SECONDS:
            videos.append({"kind": "youtube", "videoId": info["videoId"], "resolvedAt": info["resolvedAt"]})
        if VIDEO_ID.fullmatch(pinned) and (resolved.get("video:" + pinned) or {}).get("status") != "not-live" and not any(v.get("videoId") == pinned for v in videos):
            videos.append({"kind": "youtube", "videoId": pinned})
        if channel and info.get("status") != "not-live":
            videos.append({"kind": "youtube-channel", "channelId": channel})
        # ABC/NBC's retired HLS endpoints are not playback fallbacks.
        if item.get("id") in {"trusted-hls-abc-news", "trusted-hls-nbc-news"}:
            item["playbackSources"] = videos
        else:
            item["playbackSources"] = videos + [hls] if youtube_first else [hls] + videos
        if item.get("id") in CHANNELS:
            item["displayName"] = str(item.get("displayName") or "").removesuffix(" HLS")


def tv_channel_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter only the TV view; the separate YouTube library keeps its records."""
    present = {item.get("id") for item in items}
    aliases = {alias for identity, spec in CHANNELS.items() if identity in present for alias in spec[3]}
    return [item for item in items if item.get("id") not in aliases and
            (item.get("sourceType") == "hls" or bool(item.get("playbackSources")))]
