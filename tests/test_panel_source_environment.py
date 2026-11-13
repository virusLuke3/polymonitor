import json
import ast
import re
from pathlib import Path

import pytest

from data_sources import resolve_source_references, source_value
from runtime import environment


def test_private_env_is_explicit_and_process_blank_disables_source(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("PANEL_TEST_URL='https://source.example.invalid/feed?type=a&lang=b'\n")
    monkeypatch.delenv("POLYDATA_DISABLE_DOTENV")
    monkeypatch.setenv("POLYMONITOR_ENV_FILE", str(path))
    environment._file_values.cache_clear()
    assert source_value("PANEL_TEST_URL").endswith("?type=a&lang=b")
    monkeypatch.setenv("PANEL_TEST_URL", "")
    assert source_value("PANEL_TEST_URL") == ""
    assert source_value("PANEL_MISSING_URL") == ""


def test_catalog_resolution_preserves_metadata_and_missing_source(monkeypatch):
    monkeypatch.setenv("PANEL_TEST_URL", "https://source.example.invalid/feed")
    raw = {"name": "Source", "feeds": ["${PANEL_TEST_URL}", "${PANEL_MISSING_URL}"]}
    assert resolve_source_references(raw) == {
        "name": "Source", "feeds": ["https://source.example.invalid/feed", ""]}
    assert raw["feeds"][0] == "${PANEL_TEST_URL}"
    with pytest.raises(ValueError, match="Invalid source configuration"):
        resolve_source_references("${bad reference}")


def test_routes_read_env_json_and_do_not_fallback_to_another_file(monkeypatch):
    from api.clients.source_transport import _routes
    routes = {"source.example.invalid": ["socks5h://route.example.invalid:1234", ""]}
    monkeypatch.setenv("POLYMONITOR_SOURCE_ROUTES_JSON", json.dumps(routes))
    monkeypatch.setenv("POLYMONITOR_SOURCE_ROUTES_FILE", "unused-old-config.json")
    assert _routes() == routes
    monkeypatch.setenv("POLYMONITOR_SOURCE_ROUTES_JSON", "")
    with pytest.raises(ValueError, match="Move source routes"):
        _routes()
    monkeypatch.delenv("POLYMONITOR_SOURCE_ROUTES_FILE")
    assert _routes() == {}
    monkeypatch.setenv("POLYMONITOR_SOURCE_ROUTES_JSON", '{"source.example.invalid": ["file:///private"]}')
    with pytest.raises(ValueError, match="protocol"):
        _routes()


def test_youtube_missing_source_is_explicit(monkeypatch):
    from api.services.youtube_embed_service import build_youtube_embed_html
    monkeypatch.delenv("POLYMONITOR_URL_WWW_YOUTUBE_COM_D9331A", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        build_youtube_embed_html(video_id="abcdefghijk", request_origin="https://site.example.invalid")


def test_production_sources_have_no_literal_endpoint_defaults():
    root = Path(__file__).resolve().parents[1]
    namespaces = ("http://www.w3.org/", "http://www.youtube.com/xml/", "http://purl.org/", "http://www.opengis.net/", "http://www.loc.gov/mods/v3")
    findings = []
    for directory in ("scripts/api", "scripts/runtime", "agent/common"):
        for path in (root / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if re.match(r"^(?:https?|socks5h?|wss?)://[^\s]+", node.value) and not node.value.startswith(namespaces):
                    findings.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not findings, "Move source/proxy defaults into private .env: " + ", ".join(findings)
