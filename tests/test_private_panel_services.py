from pathlib import Path
import shlex

import pytest

from runtime import local_agent_model, website_link


def test_model_uses_private_config_without_exporting_unrelated_secrets(tmp_path, monkeypatch):
    interpreter = tmp_path / "bin" / "python"
    interpreter.parent.mkdir()
    interpreter.touch()
    (tmp_path / "config.json").write_text("{}")
    values = {"PYTHON": str(interpreter), "PATH": str(tmp_path), "HOST": "127.0.0.1",
              "PORT": "18003", "MEMORY_FRACTION": "0.72", "CONTEXT": "16384",
              "GPU": "0", "LIBRARY_PATH": "/configured/lib", "CUDA_HOME": "/configured/cuda"}
    config = {"POLYMONITOR_AGENT_MODEL_" + key: value for key, value in values.items()}
    config["POLYDATA_AGENT_MODEL"] = "configured-model"
    monkeypatch.setattr(local_agent_model, "configured_value", lambda key: config.get(key, ""))
    monkeypatch.setenv("PRIVATE_API_KEY", "must-not-leak")
    argv, env = local_agent_model.model_command()
    assert argv[0] == str(interpreter)
    assert argv[argv.index("--model-path") + 1] == str(tmp_path)
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert str(interpreter.parent) in env["PATH"].split(":")
    assert "PRIVATE_API_KEY" not in env
    config["POLYMONITOR_AGENT_MODEL_HOST"] = "0.0.0.0"
    with pytest.raises(ValueError, match="loopback"):
        local_agent_model.model_command()


def test_website_jump_preserves_private_forwarding_and_quoted_identity(monkeypatch):
    config = {"POLYMONITOR_TENCENT_EGRESS_IDENTITY": "/keys/web",
              "POLYMONITOR_TENCENT_HOST_KEY_ALIAS": "web.example.invalid",
              "POLYMONITOR_WEB_LINK_JUMP_NODE": "ireland",
              "POLYMONITOR_EGRESS_IDENTITY": "/keys/source with space",
              "POLYMONITOR_EGRESS_IRELAND_TARGET": "reader@jump.example.invalid",
              "POLYMONITOR_WEB_LINK_TARGET": "web@web.example.invalid",
              "POLYMONITOR_WEB_LINK_REMOTE_FORWARDS_JSON": '["127.0.0.1:18500:127.0.0.1:18502"]',
              "POLYMONITOR_WEB_LINK_LOCAL_FORWARDS_JSON": '["127.0.0.1:54443:127.0.0.1:443"]'}
    monkeypatch.setattr(website_link, "configured_value", lambda key: config.get(key, ""))
    argv = website_link.ssh_argv()
    jump = next(x.removeprefix("ProxyCommand=") for x in argv if x.startswith("ProxyCommand="))
    assert shlex.split(jump)[2] == "/keys/source with space"
    assert shlex.split(jump)[-3:] == ["-W", "%h:%p", "reader@jump.example.invalid"]
    assert argv[-1] == config["POLYMONITOR_WEB_LINK_TARGET"]
    assert "ExitOnForwardFailure=yes" in argv
    assert "ServerAliveCountMax=3" in argv
    config["POLYMONITOR_WEB_LINK_PROFILES_JSON"] = '{"interactive":{"remote":["127.0.0.1:19504:127.0.0.1:19502"],"local":[]}}'
    isolated = website_link.ssh_argv("interactive")
    assert "127.0.0.1:19504:127.0.0.1:19502" in isolated
    assert "127.0.0.1:18500:127.0.0.1:18502" not in isolated
    assert "-L" not in isolated
    with pytest.raises(ValueError, match="Invalid website forwarding profile"):
        website_link.ssh_argv("unknown")
    config["POLYMONITOR_WEB_LINK_REMOTE_FORWARDS_JSON"] = '["0.0.0.0:18500:127.0.0.1:18502"]'
    with pytest.raises(ValueError, match="Invalid POLYMONITOR_WEB_LINK_REMOTE_FORWARDS_JSON"):
        website_link.ssh_argv()


def test_missing_config_is_not_replaced_by_embedded_private_defaults(monkeypatch):
    monkeypatch.setattr(website_link, "configured_value", lambda key: "")
    with pytest.raises(ValueError, match="^Missing POLYMONITOR_TENCENT_EGRESS_IDENTITY$"):
        website_link.ssh_argv()


def test_website_profile_can_isolate_route_without_changing_other_connections(monkeypatch):
    import json
    config = {"POLYMONITOR_TENCENT_EGRESS_IDENTITY": "/keys/web",
              "POLYMONITOR_TENCENT_HOST_KEY_ALIAS": "web.example.invalid",
              "POLYMONITOR_WEB_LINK_JUMP_NODE": "ireland",
              "POLYMONITOR_EGRESS_IDENTITY": "/keys/source",
              "POLYMONITOR_EGRESS_IRELAND_TARGET": "reader@jump.example.invalid",
              "POLYMONITOR_WEB_LINK_TARGET": "web@web.example.invalid"}
    profiles = {"bulk": {"remote": ["127.0.0.1:19503:127.0.0.1:19502"], "local": [],
                         "target": "web@100.64.0.9", "jump_node": ""},
                "interactive": {"remote": [], "local": []}}
    monkeypatch.setattr(website_link, "configured_value", lambda key: config.get(key, ""))
    config["POLYMONITOR_WEB_LINK_PROFILES_JSON"] = json.dumps(profiles)
    argv = website_link.ssh_argv("bulk")
    assert argv[-1] == "web@100.64.0.9"
    assert "ProxyCommand=none" in argv and "ProxyJump=none" in argv
    assert "HostKeyAlias=web.example.invalid" in argv
    interactive = website_link.ssh_argv("interactive")
    assert interactive[-1] == "web@web.example.invalid"
    assert any("reader@jump.example.invalid" in part for part in interactive)
    for value in ("-oProxyCommand=bad", "host name", "", 23):
        profiles["bulk"]["target"] = value
        config["POLYMONITOR_WEB_LINK_PROFILES_JSON"] = json.dumps(profiles)
        with pytest.raises(ValueError, match="Invalid POLYMONITOR_WEB_LINK_TARGET"):
            website_link.ssh_argv("bulk")
    profiles["bulk"]["jump_node"] = "unknown"
    config["POLYMONITOR_WEB_LINK_PROFILES_JSON"] = json.dumps(profiles)
    with pytest.raises(ValueError, match="Unsupported website jump node"):
        website_link.ssh_argv("bulk")


def test_snapshot_failover_matches_registry_without_capturing_slow_map_or_streams():
    import re
    from deploy.render_panel_transport import public_snapshot_pattern, render
    from api.runtime_panels import RUNTIME_PANEL_MODULES
    pattern = re.compile(r"^/wm-api/(v1/)?runtime/(" + public_snapshot_pattern() + r")$")
    for panel in RUNTIME_PANEL_MODULES:
        assert pattern.fullmatch("/wm-api" + panel.route)
    for path in ("/runtime/transport/map", "/runtime/world/signals", "/runtime/world/natural-hazards/map",
                 "/runtime/lob/token/123", "/runtime/content/hls-proxy", "/auth/session", "/markets",
                 "/runtime/weather/books", "/runtime/external/arbitrary"):
        assert not pattern.fullmatch("/wm-api" + path)
    assert "__PUBLIC_PANEL_SNAPSHOT_PATHS__" not in render()


def test_reverse_link_pool_does_not_eject_all_peers_after_slow_source_reads():
    from deploy.render_panel_transport import render_upstreams
    rendered = render_upstreams(['127.0.0.1:19500', '127.0.0.1:19503'], '127.0.0.1:19504', '127.0.0.1:19505')
    assert rendered.count('max_fails=0') == 4
    assert 'server 127.0.0.1:19504;' in rendered
    assert 'server 127.0.0.1:19505 max_fails=0;' in rendered
    assert 'server 127.0.0.1:19503 backup max_fails=0;' in rendered
    assert '__POLYMONITOR_' not in rendered
    for bulk in ([], ['0.0.0.0:80'], ['127.0.0.1:65536'], ['127.0.0.1:80;extra']):
        with pytest.raises(ValueError):
            render_upstreams(bulk, '127.0.0.1:19504', '127.0.0.1:19505')
