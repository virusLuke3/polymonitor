from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agent.common.llm_client import OpenAICompatibleClient


@pytest.mark.parametrize("model", [None, "qwen3.5-9b", "Qwen3.8-27B"])
def test_qwen_returns_json_without_spending_output_budget_on_thinking(model):
    env = {"POLYDATA_AGENT_API_KEY": "EMPTY", "POLYDATA_AGENT_RUNTIME": "chat"}
    if model:
        env["POLYDATA_AGENT_MODEL"] = model
    response = Mock()
    response.json.return_value = {
        "model": model or "qwen3.5-9b",
        "choices": [{"message": {"content": '{"brief":"Evidence checked"}'}}],
        "usage": {"prompt_tokens": 24, "completion_tokens": 8, "total_tokens": 32},
    }
    with patch.dict("os.environ", env, clear=True), patch("agent.common.llm_client.requests.post", return_value=response) as post:
        client = OpenAICompatibleClient()
        result = client.complete_json([{"role": "user", "content": "Summarize the evidence as JSON."}], max_tokens=180)

    assert result == '{"brief":"Evidence checked"}'
    assert post.call_args.args == ("http://127.0.0.1:18003/v1/chat/completions",)
    body = post.call_args.kwargs["json"]
    assert body["model"] == (model or "qwen3.5-9b")
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == 180
    assert client.last_usage.total_tokens == 32


def test_explicit_provider_settings_remain_supported():
    with patch.dict("os.environ", {
        "POLYDATA_AGENT_API_KEY": "test-key",
        "POLYDATA_AGENT_API_BASE": "http://127.0.0.1:9999/v1",
        "POLYDATA_AGENT_MODEL": "custom-model",
        "POLYDATA_AGENT_RUNTIME": "agents",
    }, clear=True):
        client = OpenAICompatibleClient()
    assert (client.api_base, client.model, client.runtime) == ("http://127.0.0.1:9999/v1", "custom-model", "agents")


def test_qwen_agents_sdk_uses_the_same_non_thinking_request_contract():
    with patch.dict("os.environ", {"POLYDATA_AGENT_MODEL": "qwen3.5-9b"}, clear=True), patch(
        "agent.common.llm_client.ModelSettings", SimpleNamespace,
    ):
        settings = OpenAICompatibleClient()._model_settings(180)
    assert settings.max_tokens == 180
    assert settings.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
