import importlib
import sys
from pathlib import Path

import pytest


def _reload_config(monkeypatch, *, polygon_url=None, legacy_url=None):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    if polygon_url is None:
        monkeypatch.delenv("POLYMARKET_RPC_URL", raising=False)
    else:
        monkeypatch.setenv("POLYMARKET_RPC_URL", polygon_url)
    if legacy_url is None:
        monkeypatch.delenv("NODE_URL", raising=False)
    else:
        monkeypatch.setenv("NODE_URL", legacy_url)
    sys.modules.pop("config", None)
    sys.modules.pop("data_sources", None)
    return importlib.import_module("config")


def test_self_hosted_polygon_rpc_has_priority(monkeypatch):
    config = _reload_config(
        monkeypatch,
        polygon_url="http://127.0.0.1:28545",
        legacy_url="https://legacy-provider.invalid/key",
    )

    assert config.get_rpc_url() == "http://127.0.0.1:28545"


def test_legacy_node_url_is_not_a_fallback(monkeypatch):
    config = _reload_config(
        monkeypatch,
        legacy_url="https://legacy-provider.invalid/key",
    )

    try:
        resolved = config.get_rpc_url()
    except RuntimeError as exc:
        assert "POLYMARKET_RPC_URL is required" in str(exc)
    else:
        assert resolved != "https://legacy-provider.invalid/key"


def test_remote_polygon_rpc_is_rejected(monkeypatch):
    with pytest.raises(RuntimeError, match="local SSH tunnel"):
        _reload_config(
            monkeypatch,
            polygon_url="https://hosted-provider.invalid/polygon",
        ).get_rpc_url()


@pytest.mark.parametrize(
    "polygon_url",
    [
        "http://127.0.0.1:28545",
        "http://localhost:28545",
        "http://[::1]:28545",
    ],
)
def test_loopback_polygon_tunnel_endpoints_are_allowed(monkeypatch, polygon_url):
    config = _reload_config(monkeypatch, polygon_url=polygon_url)

    assert config.get_rpc_url() == polygon_url
