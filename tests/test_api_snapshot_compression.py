import gzip
import json

import pytest
from flask import Flask, Response

from api.http import PUBLIC_LARGE_SNAPSHOTS, compress_public_snapshot, register_http_hooks


@pytest.mark.parametrize('path', sorted(PUBLIC_LARGE_SNAPSHOTS))
def test_public_snapshot_roundtrip_preserves_clocks_and_cache_headers(path):
    app = Flask(__name__)
    register_http_hooks(app, {'https://polymonitor.club'})
    body = json.dumps({'generatedAt': '2026-11-10T00:00:00Z', 'status': 'stale',
                       'items': [{'id': i, 'value': 'stored observation'} for i in range(400)]}).encode()

    @app.get(path)
    def snapshot():
        response = Response(body, mimetype='application/json')
        response.headers['Cache-Control'] = 'no-store'
        response.vary.add('X-Test-Scope')
        response.set_etag('stored-source-revision')
        return response

    client = app.test_client()
    response = client.get(path, headers={'Accept-Encoding': 'gzip', 'Origin': 'https://polymonitor.club'})
    assert response.status_code == 200
    assert response.headers['Content-Encoding'] == 'gzip'
    assert gzip.decompress(response.data) == body
    assert len(response.data) < len(body) / 4
    assert response.content_length == len(response.data)
    assert set(response.vary) == {'Accept-Encoding', 'Origin', 'X-Test-Scope'}
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.get_etag() == ('stored-source-revision', True)
    for accept in ('', 'gzip;q=0, br;q=0, identity;q=1'):
        plain = client.get(path, headers={'Accept-Encoding': accept})
        assert 'Content-Encoding' not in plain.headers
        assert plain.data == body
        assert 'Accept-Encoding' in plain.vary


def test_brotli_negotiation_and_optional_dependency_fallback(monkeypatch):
    import api.http as http
    brotli = pytest.importorskip('brotli')
    app = Flask(__name__)
    body = json.dumps({'generatedAt': '2026-11-10T08:47:47Z', 'rows': ['original source data'] * 300}).encode()
    for accept, encoding in [('gzip, br', 'br'), ('gzip;q=1, br;q=0.5', 'gzip'), ('br', 'br')]:
        with app.test_request_context('/runtime/weather/temperature-monitor', headers={'Accept-Encoding': accept}):
            response = compress_public_snapshot(Response(body, mimetype='application/json'))
            assert response.headers['Content-Encoding'] == encoding
            assert (brotli.decompress if encoding == 'br' else gzip.decompress)(response.data) == body
    monkeypatch.setattr(http, 'brotli', None)
    with app.test_request_context('/runtime/weather/temperature-monitor', headers={'Accept-Encoding': 'gzip, br'}):
        response = compress_public_snapshot(Response(body, mimetype='application/json'))
        assert response.headers['Content-Encoding'] == 'gzip'
        assert gzip.decompress(response.data) == body
    with app.test_request_context('/runtime/weather/temperature-monitor', headers={'Accept-Encoding': 'br'}):
        response = compress_public_snapshot(Response(body, mimetype='application/json'))
        assert 'Content-Encoding' not in response.headers
        assert response.data == body


@pytest.mark.parametrize('kind', ['private', 'post', 'error', 'small', 'stream', 'encoded', 'cookie'])
def test_non_snapshot_or_non_transformable_responses_are_untouched(kind):
    app = Flask(__name__)
    path = '/product/private' if kind == 'private' else '/runtime/crypto/order-flow'
    method = 'POST' if kind == 'post' else 'GET'
    with app.test_request_context(path, method=method, headers={'Accept-Encoding': 'gzip'}):
        body = b'{}' if kind == 'small' else b'x' * 3000
        response = Response(iter([body]) if kind == 'stream' else body,
                            status=503 if kind == 'error' else 200, mimetype='application/json')
        if kind == 'encoded':
            response.headers['Content-Encoding'] = 'br'
        if kind == 'cookie':
            response.set_cookie('session', 'private-session')
        before = dict(response.headers)
        compress_public_snapshot(response)
        assert dict(response.headers) == before or kind == 'small' and response.vary == {'Accept-Encoding'}
        assert response.get_data() == body
