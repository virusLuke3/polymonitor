import json
from types import SimpleNamespace

from api.services import live_video_playback_service as tv


def page(channel, **details):
    return 'var ytInitialPlayerResponse = ' + json.dumps({
        'videoDetails': {'videoId': 'abcDEF12345', 'channelId': channel, **details},
        'playabilityStatus': {'status': 'OK', 'playableInEmbed': True},
    }) + ';'


def test_completed_live_recordings_and_wrong_channel_are_rejected():
    assert tv.parse_current_live(page('owner', isLiveContent=True), 'owner')['status'] == 'not-live'
    assert tv.parse_current_live(page('other', isLive=True), 'owner')['status'] == 'error'
    assert tv.parse_current_live(page('owner', isLive=True), 'owner')['status'] == 'live'
    assert tv.parse_current_live('consent required', 'owner')['status'] == 'error'


def test_same_channel_order_and_view_only_deduplication():
    items = [{'id': 'trusted-hls-euronews', 'sourceType': 'hls', 'hlsUrl': 'https://test/live.m3u8'},
             {'id': 'trusted-youtube-euronews', 'sourceType': 'youtube'},
             {'id': 'trusted-hls-dw', 'sourceType': 'hls', 'hlsUrl': 'https://dw/live.m3u8'}]
    tv.attach_playback_sources(items, {})
    assert [s['kind'] for s in items[0]['playbackSources']] == ['youtube', 'hls']
    assert [s['kind'] for s in items[2]['playbackSources']] == ['hls', 'youtube', 'youtube-channel']
    assert len(tv.tv_channel_items(items)) == 2
    assert len(items) == 3  # YouTube library is unchanged.


def test_resolution_cadence_failure_does_not_renew_live_time(monkeypatch):
    now = [1000000.0]
    monkeypatch.setattr(tv.time, 'time', lambda: now[0])
    channel = 'UCIALMKvObZNtJ6AmdCLP7Lg'
    monkeypatch.setattr(tv, 'CHANNELS', {'one': (channel, '', False, ())})
    values, calls = {}, []
    store = SimpleNamespace(get_stale=lambda ns, key: values.get(key), set=lambda ns, key, value, ttl: values.update({key: value}))
    def fetch(*args, **kwargs):
        calls.append(args[0])
        if len(calls) > 1:
            raise TimeoutError()
        return page(channel, isLive=True)
    deps = SimpleNamespace(snapshot_store=store, http_text_get=fetch)
    tv.refresh_live_channels(deps)
    first = values[channel]['resolvedAt']
    now[0] += 900
    tv.refresh_live_channels(deps)
    assert len(calls) == 1
    now[0] += 21600
    tv.refresh_live_channels(deps)
    assert values[channel]['resolvedAt'] == first
    assert values[channel]['status'] == 'error'
    now[0] += 36 * 3600
    tv.refresh_live_channels(deps)
    assert 'videoId' not in values[channel]


def test_known_finished_pinned_source_is_removed_from_candidates():
    items = [{"id": "trusted-hls-euronews", "sourceType": "hls", "hlsUrl": "https://test/live.m3u8"}]
    tv.attach_playback_sources(items, {"video:pykpO5kQJ98": {"status": "not-live"}})
    assert [source["kind"] for source in items[0]["playbackSources"]] == ["hls"]
    assert tv.parse_current_live(page("owner", isLive=True), "", "wrongID1234")["status"] == "error"


def test_failed_catalog_refresh_preserves_station_and_original_fetch_clock(monkeypatch):
    from api.services import live_video_source_service as source
    now = [1000000.0]
    monkeypatch.setattr(source.time, "time", lambda: now[0])
    values = {}
    store = SimpleNamespace(get_stale=lambda ns, key: values.get(key), set=lambda ns, key, value, ttl: values.update({key: value}))
    deps = SimpleNamespace(snapshot_store=store)
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise TimeoutError("temporary outage")
        return "#EXTM3U\n#EXTINF:-1,Station\nhttps://tv.example/live.m3u8\n"
    monkeypatch.setattr(source, "_http_text_get", fetch)
    first = source._iptv_directory(deps, "news", "https://directory.example", "original")
    now[0] += 900
    assert source._iptv_directory(deps, "news", "https://directory.example", "later")["fetchedAt"] == "original"
    assert len(calls) == 1
    now[0] += 86400
    stale = source._iptv_directory(deps, "news", "https://directory.example", "later")
    assert stale["items"] == first["items"] and stale["fetchedAt"] == "original"
    assert stale["error"]
