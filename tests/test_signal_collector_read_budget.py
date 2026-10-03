from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from api.config import ClickHouseSettings
from api.context import RuntimeResources
from api.services import clickhouse_orderfilled_service as reads
from runtime.signals_watcher import SignalsWatcher


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return b'{"value":1}\n'


def context(*, collection=False, http=True):
    resources = RuntimeResources(clickhouse=ClickHouseSettings(
        http_url="http://127.0.0.1:18123" if http else "",
    ))
    if collection:
        resources.clickhouse_read_timeout_seconds = 10.0
    return {"app": SimpleNamespace(logger=Mock()), "_resources": resources}


def test_collection_transport_budget_does_not_raise_query_resource_limits():
    ctx = context(collection=True)
    with patch.object(reads, "urlopen", return_value=Response()) as transport:
        assert reads._query_json_rows(ctx, "SELECT 1 FORMAT JSONEachRow", timeout_seconds=5) == [{"value": 1}]
    request = transport.call_args.args[0]
    params = parse_qs(urlparse(request.full_url).query)
    assert transport.call_args.kwargs["timeout"] == 10
    assert params["max_execution_time"] == ["6"]
    assert params["readonly"] == ["1"]
    assert params["max_threads"] == ["2"]
    assert params["max_bytes_to_read"] == ["536870912"]
    assert params["cancel_http_readonly_queries_on_client_close"] == ["1"]


def test_serving_api_keeps_its_short_read_deadline():
    ctx = context()
    with patch.object(reads, "urlopen", return_value=Response()) as transport:
        assert reads._query_json_rows(ctx, "SELECT 1") == [{"value": 1}]
    assert transport.call_args.kwargs["timeout"] == 1.8
    params = parse_qs(urlparse(transport.call_args.args[0].full_url).query)
    assert params["max_execution_time"] == ["2"]
    assert ctx["_resources"].clickhouse_read_timeout_seconds is None


def test_collection_timeout_releases_slot_and_rejects_partial_response():
    ctx = context(collection=True)
    with patch.object(reads, "urlopen", side_effect=TimeoutError):
        assert reads._query_json_rows(ctx, "SELECT 1") is None
    response = Response()
    response.read = lambda: b'{"value":1}\nCode: 159 execution timeout\n'
    with patch.object(reads, "urlopen", return_value=response):
        assert reads._query_json_rows(ctx, "SELECT 1") is None
    with patch.object(reads, "urlopen", return_value=Response()):
        assert reads._query_json_rows(ctx, "SELECT 1") == [{"value": 1}]


def test_docker_collection_budget_keeps_server_execution_cap():
    ctx = context(collection=True, http=False)
    with patch.object(reads.shutil, "which", return_value="docker"), patch.object(
        reads.subprocess, "run", return_value=SimpleNamespace(stdout='{"value":1}\n')
    ) as transport:
        assert reads._query_json_rows(ctx, "SELECT 1") == [{"value": 1}]
    assert transport.call_args.kwargs["timeout"] == 10
    command = transport.call_args.args[0]
    assert command[command.index("--max_execution_time") + 1] == "6"


def test_only_watcher_owned_runtime_receives_collection_budget():
    watcher = SignalsWatcher.__new__(SignalsWatcher)
    watcher.settings = object()
    watcher.component = "whales"
    runtime = SimpleNamespace(resources=RuntimeResources(), signal_context={})
    with patch("api.runtime.ServiceRuntime", return_value=runtime) as constructor:
        assert watcher.service_context() is runtime.signal_context
        assert watcher.service_context() is runtime.signal_context
    constructor.assert_called_once()
    assert runtime.resources.clickhouse_read_timeout_seconds == 10
    assert RuntimeResources().clickhouse_read_timeout_seconds is None
