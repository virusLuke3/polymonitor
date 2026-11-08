import pytest

from runtime import source_egress


@pytest.mark.parametrize("node", ["ireland", "usla"])
def test_exit_uses_only_selected_project_node_and_preserves_ssh_options(monkeypatch, node):
    values = {
        "POLYMONITOR_EGRESS_IDENTITY": "/keys/existing",
        "POLYMONITOR_EGRESS_IRELAND_LISTEN": "127.0.0.1:10001",
        "POLYMONITOR_EGRESS_IRELAND_TARGET": "reader@ireland.example.invalid",
        "POLYMONITOR_EGRESS_USLA_LISTEN": "127.0.0.1:10002",
        "POLYMONITOR_EGRESS_USLA_TARGET": "reader@usla.example.invalid",
        "POLYMONITOR_EGRESS_LISTEN": "legacy-must-not-win",
        "POLYMONITOR_EGRESS_TARGET": "legacy-must-not-win",
    }
    monkeypatch.setattr(source_egress, "configured_value", lambda name: values.get(name, ""))
    command = source_egress.ssh_argv(node)
    assert command[:5] == ["/usr/bin/ssh", "-N", "-T", "-i", "/keys/existing"]
    assert command[-3:] == ["-D", values[f"POLYMONITOR_EGRESS_{node.upper()}_LISTEN"],
                           values[f"POLYMONITOR_EGRESS_{node.upper()}_TARGET"]]
    assert command[5:-3:2] == ["-o"] * 8
    assert command[6:-3:2] == ["IdentitiesOnly=yes", "BatchMode=yes", "ConnectTimeout=12",
                              "ExitOnForwardFailure=yes", "ServerAliveInterval=15",
                              "ServerAliveCountMax=3", "ProxyCommand=none", "ProxyJump=none"]


def test_missing_node_config_does_not_fallback_or_expose_values(monkeypatch):
    monkeypatch.setattr(source_egress, "configured_value", lambda name: "" if name.endswith("_TARGET") else "private-value")
    with pytest.raises(ValueError, match="^Missing POLYMONITOR_EGRESS_IRELAND_TARGET$"):
        source_egress.ssh_argv("ireland")
    with pytest.raises(ValueError, match="^Unsupported source egress node$"):
        source_egress.ssh_argv("new-node")


def test_main_loads_shared_environment_then_execs_without_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(source_egress.sys, "argv", ["source_egress.py", "--node", "ireland"])
    monkeypatch.setattr(source_egress, "load_environment", lambda: calls.append("env"))
    monkeypatch.setattr(source_egress, "ssh_argv", lambda node: calls.append(node) or ["/usr/bin/ssh", "-N"])
    monkeypatch.setattr(source_egress.os, "execv", lambda program, argv: calls.append((program, argv)))
    source_egress.main()
    assert calls == ["env", "ireland", ("/usr/bin/ssh", ["/usr/bin/ssh", "-N"])]
