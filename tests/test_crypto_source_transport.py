"""Exercise the collector's real SOCKS transport without an external provider."""
import socketserver
import threading
from contextlib import closing
from unittest.mock import Mock

import pytest
import requests

from api.clients.http_client import _read_json_response
from api.context import RuntimeResources
from runtime.crypto_strategy_watcher import get
from runtime.defi_token_watch_watcher import DefiTokenWatchWatcher


def test_crypto_and_defi_can_use_configured_socks_egress(monkeypatch):
    observed = []

    class SocksHandler(socketserver.StreamRequestHandler):
        def handle(self):
            version, count = self.rfile.read(2)
            assert version == 5
            self.rfile.read(count)
            self.wfile.write(b'\x05\x00')
            assert self.rfile.read(4) == b'\x05\x01\x00\x03'
            host = self.rfile.read(self.rfile.read(1)[0]).decode()
            port = int.from_bytes(self.rfile.read(2), 'big')
            self.wfile.write(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x50')
            request_line = self.rfile.readline().decode().strip()
            while self.rfile.readline() != b'\r\n':
                pass
            observed.append((host, port, request_line))
            self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')

    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), SocksHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        proxy = f'socks5h://127.0.0.1:{server.server_address[1]}'
        monkeypatch.setenv('POLYDATA_API_HTTP_PROXY_URL', proxy)
        monkeypatch.setenv('POLYDATA_API_HTTP_TRUST_ENV_PROXY', '1')
        monkeypatch.setenv('HTTP_PROXY', proxy)
        monkeypatch.setenv('http_proxy', proxy)
        monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
        monkeypatch.setenv('no_proxy', '127.0.0.1,localhost')
        try:
            with closing(RuntimeResources()) as resources:
                context = {'requests': requests, '_resources': resources}
                assert get(context, 'http://crypto-source.invalid/quotes', {'symbol': 'BTC USDT'}) == {'ok': True}
                assert len(resources.http_sessions) == 1
            assert resources.http_sessions == []
            watcher = DefiTokenWatchWatcher.__new__(DefiTokenWatchWatcher)
            with requests.Session() as watcher.requests:
                watcher.requests.trust_env = True
                assert watcher.http_json_get('http://defi-source.invalid/tokens') == {'ok': True}
        finally:
            server.shutdown()
            thread.join(2)
    assert observed == [
        ('crypto-source.invalid', 80, 'GET /quotes?symbol=BTC+USDT HTTP/1.1'),
        ('defi-source.invalid', 80, 'GET /tokens HTTP/1.1'),
    ]


def test_bounded_json_stops_reading_and_closes_oversize_response():
    response = Mock()
    def chunks():
        yield b'12345'
        yield b'67890'
        pytest.fail('reader continued after the size limit')
    response.iter_content.side_effect = lambda **_: chunks()
    with pytest.raises(ValueError, match='SOURCE_RESPONSE_TOO_LARGE'):
        _read_json_response(response, 8)
    response.close.assert_called_once()


@pytest.mark.parametrize('body', [b'not json', b'{"ok":true}'])
def test_bounded_json_closes_successful_and_malformed_responses(body):
    response = Mock()
    response.iter_content.return_value = [body]
    if body.startswith(b'{'):
        assert _read_json_response(response, 100) == {'ok': True}
    else:
        with pytest.raises(ValueError):
            _read_json_response(response, 100)
    response.close.assert_called_once()
