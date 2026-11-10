"""Start the private website link, independently of collector proxy connections."""
from __future__ import annotations

import ipaddress
import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.environment import configured_value


def required(name: str) -> str:
    value = configured_value(name).strip()
    if not value:
        raise ValueError(f"Missing {name}")
    return value


def target(name: str, override: str | None = None) -> str:
    value = required(name) if override is None else override
    if not isinstance(value, str) or not value:
        raise ValueError(f"Invalid {name}")
    if value.startswith("-") or any(c.isspace() for c in value):
        raise ValueError(f"Invalid {name}")
    return value


def ssh_argv(profile: str | None = None) -> list[str]:
    overrides = None
    if profile:
        try:
            profiles = json.loads(required("POLYMONITOR_WEB_LINK_PROFILES_JSON"))
            overrides = profiles[profile]
            if (not isinstance(overrides, dict)
                    or not {"remote", "local"} <= set(overrides)
                    or set(overrides) - {"remote", "local", "target", "jump_node", "http_proxy"}
                    or ("target" in overrides and overrides["target"] is None)
                    or ("jump_node" in overrides and not isinstance(overrides["jump_node"], str))
                    or ("http_proxy" in overrides and not isinstance(overrides["http_proxy"], str))):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError("Invalid website forwarding profile") from None
    options = ["-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=10",
               "-o", "ServerAliveCountMax=3", "-o", "ExitOnForwardFailure=yes",
               "-o", "IPQoS=none"]
    command = ["/usr/bin/ssh", "-C", "-N", "-T", "-i",
               required("POLYMONITOR_TENCENT_EGRESS_IDENTITY"), *options,
               "-o", "HostKeyAlias=" + required("POLYMONITOR_TENCENT_HOST_KEY_ALIAS")]
    node = (overrides.get("jump_node", configured_value("POLYMONITOR_WEB_LINK_JUMP_NODE"))
            if overrides is not None else configured_value("POLYMONITOR_WEB_LINK_JUMP_NODE")).strip()
    proxy = overrides.get("http_proxy", "") if overrides is not None else ""
    if proxy:
        try:
            parsed = urlsplit(proxy)
            if (node or parsed.scheme != "http" or not parsed.hostname
                    or not ipaddress.ip_address(parsed.hostname).is_loopback
                    or parsed.username or parsed.password or parsed.path not in {"", "/"}
                    or parsed.query or parsed.fragment or not parsed.port or not 1 <= parsed.port <= 65535):
                raise ValueError()
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            connect = ["/usr/bin/nc", "-X", "connect", "-x", f"{host}:{parsed.port}", "%h", "%p"]
        except (TypeError, ValueError):
            raise ValueError("Website HTTP proxy must be an explicit loopback endpoint without a jump") from None
        command += ["-o", "ProxyCommand=" + shlex.join(connect), "-o", "ProxyJump=none"]
    elif node:
        if node not in {"ireland", "usla"}:
            raise ValueError("Unsupported website jump node")
        jump = ["/usr/bin/ssh", "-i", required("POLYMONITOR_EGRESS_IDENTITY"), *options,
                "-o", "ProxyCommand=none", "-o", "ProxyJump=none", "-W", "%h:%p",
                target("POLYMONITOR_EGRESS_" + node.upper() + "_TARGET")]
        command += ["-o", "ProxyCommand=" + shlex.join(jump)]
    else:
        command += ["-o", "ProxyCommand=none", "-o", "ProxyJump=none"]
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
    command.append(target("POLYMONITOR_WEB_LINK_TARGET",
                          overrides.get("target") if overrides is not None else None))
    return command


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile")
    argv = ssh_argv(parser.parse_args().profile)
    os.execv(argv[0], argv)
