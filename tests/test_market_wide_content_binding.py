"""Exercise the worker's real dependency assembly, not a hand-wired news helper."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from agent.market_wide.service import _build_agent_context
from agent.market_wide.snapshot import DEFAULT_LENSES, build_market_wide_seed_payload
from api.config import load_api_settings
from api.runtime import ServiceRuntime
from api.services import query_service


@pytest.mark.parametrize("lens", DEFAULT_LENSES)
@pytest.mark.parametrize("count", [0, 15])
def test_runtime_news_reaches_market_wide_model_context(monkeypatch, tmp_path, lens, count):
    articles = [
        {
            "title": f"Official release {index}",
            "source": "Federal Reserve Board",
            "summary": "Isolated test excerpt.",
            "publishedAt": "2026-11-05T18:00:00Z",
        }
        for index in range(count)
    ]
    reader = Mock(return_value={"items": articles, "status": "partial" if articles else "empty"})
    monkeypatch.setattr(query_service, "get_latest_content_snapshot", reader)
    settings = replace(load_api_settings(), snapshot_sqlite_path=str(tmp_path / "snapshots.sqlite3"))
    connection = Mock(side_effect=AssertionError("This wiring test must not query a real database"))

    with ServiceRuntime(settings, connection_factory=connection) as runtime:
        helpers = dict(runtime.agent_snapshot_context)
        # Only unrelated inputs are stubbed; the content binding remains the one
        # used by the production seed and the shared public-content reader.
        helpers.update(
            get_active_markets_snapshot=lambda *_: {"items": []},
            get_market_groups_payload=lambda **_: {"items": []},
            get_recent_trades_snapshot=lambda *_: [],
            get_recent_oracle_snapshot=lambda *_: [],
            get_cached_json=lambda *_: None,
        )
        payload = build_market_wide_seed_payload(helpers, lens)
        context = _build_agent_context(payload, lens, [])

        reader.assert_called_once_with(runtime.query_context, limit=12, days=7)
        assert payload["content"] == articles[:12]
        assert context["metrics"]["contentItems"] == min(count, 12)
        assert context["content"] == articles[:6]
        connection.assert_not_called()
