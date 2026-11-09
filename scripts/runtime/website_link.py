"""Start the private website link, independently of collector proxy connections."""
from __future__ import annotations

import ipaddress
import argparse
import json
import os
import shlex
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.environment import configured_value


def required(name: str) -> str:
    value = configured_value(name).strip()
    if not value:
        raise ValueError(f"Missing {name}")
    return value


def target(name: str) -> str:
    value = required(name)
    if value.startswith("-") or any(c.isspace() for c in value):
        raise ValueError(f"Invalid {name}")
    return value


def ssh_argv(profile: str | None = None) -> list[str]:
    options = ["-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=10",
               "-o", "ServerAliveCountMax=3", "-o", "ExitOnForwardFailure=yes",
               "-o", "IPQoS=none"]
    command = ["/usr/bin/ssh", "-C", "-N", "-T", "-i",
               required("POLYMONITOR_TENCENT_EGRESS_IDENTITY"), *options,
               "-o", "HostKeyAlias=" + required("POLYMONITOR_TENCENT_HOST_KEY_ALIAS")]
    node = configured_value("POLYMONITOR_WEB_LINK_JUMP_NODE").strip()
    if node:
        if node not in {"ireland", "usla"}:
            raise ValueError("Unsupported website jump node")
        jump = ["/usr/bin/ssh", "-i", required("POLYMONITOR_EGRESS_IDENTITY"), *options,
                "-o", "ProxyCommand=none", "-o", "ProxyJump=none", "-W", "%h:%p",
                target("POLYMONITOR_EGRESS_" + node.upper() + "_TARGET")]
        command += ["-o", "ProxyCommand=" + shlex.join(jump)]
    else:
        command += ["-o", "ProxyCommand=none", "-o", "ProxyJump=none"]
    overrides = None
    if profile:
        try:
            profiles = json.loads(required("POLYMONITOR_WEB_LINK_PROFILES_JSON"))
            overrides = profiles[profile]
            if not isinstance(overrides, dict) or set(overrides) != {"remote", "local"}:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError("Invalid website forwarding profile") from None
    for direction, flag in (("REMOTE", "-R"), ("LOCAL", "-L")):
        name = "POLYMONITOR_WEB_LINK_" + direction + "_FORWARDS_JSON"
        try:
            forwards = overrides[direction.lower()] if overrides is not None else json.loads(required(name))
            if not isinstance(forwards, list) or len(forwards) > 8:
                raise ValueError()
            for item in forwards:
                # This bridge exposes only private loopback listeners/consumers.
                bind, port, dest, dest_port = item.split(":")
                if not all(ipaddress.ip_address(host).is_loopback for host in (bind, dest)):
                    raise ValueError()
                if not all(1 <= int(p) <= 65535 for p in (port, dest_port)):
                    raise ValueError()
                command += [flag, item]
        except (TypeError, ValueError, AttributeError):
            raise ValueError(f"Invalid {name}") from None
    command.append(target("POLYMONITOR_WEB_LINK_TARGET"))
    return command


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile")
    argv = ssh_argv(parser.parse_args().profile)
    os.execv(argv[0], argv)
