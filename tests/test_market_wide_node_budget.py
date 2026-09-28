import os
from types import SimpleNamespace
from unittest.mock import patch

from agent.market_wide.graph import _call_json_node, _usage_total


class Client:
    model = "Qwen3.8-27B"
    last_usage = SimpleNamespace(runtime="chat", input_tokens=10, output_tokens=20, total_tokens=30, input_chars=40)

    def complete_json(self, messages, *, max_tokens, workflow_name):
        self.budget = max_tokens
        return self.output


def test_node_budget_can_be_configured_without_changing_prompts():
    client = Client()
    client.output = '{"findings": []}'
    with patch.dict(os.environ, {"POLYDATA_AGENT_MARKET_WIDE_SPECIALIST_MAX_TOKENS": "2048"}):
        result, event = _call_json_node(client, "microstructure", [], max_tokens=520, run_id="test")
    assert client.budget == 2048
    assert event["maxOutputTokens"] == 2048
    assert result == {"findings": []}


def test_invalid_json_still_records_model_usage():
    client = Client()
    client.output = '{"findings": ['
    result, event = _call_json_node(client, "panel_writer", [], max_tokens=950, run_id="test")
    assert result == {}
    assert event["status"] == "error"
    assert _usage_total([event]) == {"requests": 1, "inputTokens": 10, "outputTokens": 20, "totalTokens": 30}


def test_writer_budget_is_bounded():
    client = Client()
    client.output = '{}'
    with patch.dict(os.environ, {"POLYDATA_AGENT_MARKET_WIDE_WRITER_MAX_TOKENS": "99999"}):
        _call_json_node(client, "panel_writer", [], max_tokens=950, run_id="test")
    assert client.budget == 8192
