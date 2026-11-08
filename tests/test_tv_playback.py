import json
import runpy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

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


def test_reviewed_alternative_stays_in_same_channel_and_proxy_is_bounded(monkeypatch):
    from api.services import hls_proxy_service as proxy
    station = {'id': 'trusted-hls-dw', 'sourceType': 'hls', 'hlsUrl': 'https://primary.example/news/master.m3u8',
               'hlsAlternates': [{'url': 'https://alternate.example/dw/playlist.m3u8', 'proxy': True}],
               'playbackTier': 'trusted-hls'}
    tv.attach_playback_sources([station], {})
    assert [x['url'] for x in station['playbackSources'] if x['kind'] == 'hls'] == [station['hlsUrl'], station['hlsAlternates'][0]['url']]
    assert station['playbackSources'][1]['proxy'] is True
    monkeypatch.setattr(proxy, 'TRUSTED_HLS_SOURCES', [station])
    assert proxy.is_allowed_hls_url('https://alternate.example/dw/segment.ts')
    assert not proxy.is_allowed_hls_url('https://alternate.example/unrelated/segment.ts')
    assert not proxy.is_allowed_hls_url('https://arbitrary.example/dw/segment.ts')


@pytest.mark.parametrize('configure_english_backup', [False, True])
def test_dw_english_never_uses_retired_arabic_configuration(monkeypatch, configure_english_backup):
    import data_sources
    from api.services import hls_proxy_service as proxy, trusted_hls_sources as sources
    english = 'https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/master.m3u8'
    arabic = 'https://dwamdstream103.akamaized.net/hls/live/2015526/dwstream103/master.m3u8'
    values = {
        'POLYMONITOR_TV_DW_HLS_URL': 'https://english-main.example/playlist/master.m3u8',
        'POLYMONITOR_URL_DWAMDSTREAM103_AKAMAIZED_NET_HLS_LIVE_2015526_DWSTREAM103_MASTER_M3U8_26F26D': arabic,
        'POLYMONITOR_TV_DW_AKAMAI_RESOURCE_PATHS': '["/hls/live/2015526-b/dwstream103/"]',
    }
    if configure_english_backup:
        values['POLYMONITOR_TV_DW_ENGLISH_BACKUP_HLS_URL'] = english
        values['POLYMONITOR_TV_DW_ENGLISH_BACKUP_RESOURCE_PATHS'] = '["/hls/live/2015525-b/dwstream102/"]'
    monkeypatch.setattr(data_sources, 'source_value', lambda key: values.get(key, ''))
    catalog = runpy.run_path(sources.__file__)['TRUSTED_HLS_SOURCES']
    dw = dict(next(row for row in catalog if row['id'] == 'trusted-hls-dw'), sourceType='hls', playbackTier='trusted-hls')
    assert dw['language'] == 'en'
    tv.attach_playback_sources([dw], {})
    urls = [row['url'] for row in dw['playbackSources'] if row['kind'] == 'hls']
    assert urls == [values['POLYMONITOR_TV_DW_HLS_URL']] + ([english] if configure_english_backup else [])
    assert arabic not in urls
    monkeypatch.setattr(proxy, 'TRUSTED_HLS_SOURCES', [dw])
    assert not proxy.is_allowed_hls_url(arabic)
    assert proxy.is_allowed_hls_url(english) is configure_english_backup
    assert not proxy.is_allowed_hls_url('https://dwamdstream102.akamaized.net/unrelated/segment.ts')


def test_resolution_cadence_failure_does_not_renew_live_time(monkeypatch):
    now = [1000000.0]
    monkeypatch.setattr(tv.time, 'time', lambda: now[0])
    channel = 'UCIALMKvObZNtJ6AmdCLP7Lg'
    monkeypatch.setattr(tv, 'CHANNELS', {'one': (channel, '', False, ())})
    values, calls = {}, []
    store = SimpleNamespace(get_stale=lambda ns, key: values.get(key), set=lambda ns, key, value, ttl: values.update({key: value}))
    def fetch(*args, **kwargs):
        assert kwargs['headers']['Cookie'] == 'SOCS=CAI'
        assert kwargs['timeout'] == 30
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


def test_player_access_challenge_is_not_a_confirmed_end():
    html = page('owner', isLive=True).replace('"status": "OK"', '"status": "LOGIN_REQUIRED"')
    assert tv.parse_current_live(html, 'owner')['status'] == 'error'


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


def test_media_redirect_keeps_original_deadline_and_validates_every_hop(monkeypatch):
    from api.services import hls_proxy_service as proxy
    station = {'hlsUrl': 'https://station.example/playlist/master.m3u8',
               'hlsProxyAdditionalPaths': ['/media/']}
    monkeypatch.setattr(proxy, 'TRUSTED_HLS_SOURCES', [station])
    monkeypatch.setattr(proxy, 'source_session', lambda: nullcontext(object()))
    calls = []
    destinations = ['/media/chunk.ts']
    def read(session, url, callback, **kwargs):
        calls.append((url, kwargs['deadline']))
        assert kwargs['allow_redirects'] is False
        redirect = destinations.pop(0) if destinations else None
        response = SimpleNamespace(status_code=307 if redirect else 200,
            headers={'Location': redirect} if redirect else {'Content-Type': 'video/mp2t'},
            raise_for_status=lambda: None, iter_content=lambda **_: iter([b'media']))
        return callback(response)
    monkeypatch.setattr(proxy, 'read_with_retry', read)
    assert proxy.fetch_hls_resource('https://station.example/playlist/part.ts') == (b'media', 'video/mp2t', 200)
    assert len(calls) == 2 and calls[0][1] == calls[1][1]
    for destination in ['https://unknown.example/media/a.ts', '/unrelated/a.ts']:
        destinations[:] = [destination]
        calls.clear()
        with pytest.raises(proxy.HlsProxyError, match='allowlist'):
            proxy.fetch_hls_resource('https://station.example/playlist/part.ts')
        assert len(calls) == 1
    destinations[:] = ['/media/chunk.ts'] * 4
    calls.clear()
    with pytest.raises(proxy.HlsProxyError, match='redirect limit'):
        proxy.fetch_hls_resource('https://station.example/playlist/part.ts')
    assert len(calls) == 4


def test_invalid_optional_resource_paths_do_not_break_other_stations(monkeypatch):
    from api.services import trusted_hls_sources as sources
    for invalid in ['broken json', '{}', 'null', '["/", "/../", 3]']:
        monkeypatch.setattr(sources, 'source_value', lambda key: invalid)
        assert sources._resource_paths('TEST') == []
    monkeypatch.setattr(sources, 'source_value', lambda key: '["/reviewed-channel/"]')
    assert sources._resource_paths('TEST') == ['/reviewed-channel/']
