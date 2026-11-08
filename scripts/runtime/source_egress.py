"""Start an existing isolated SSH exit from the project's single environment."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.environment import configured_value, load_environment


def ssh_argv(node: str) -> list[str]:
    if node not in {"ireland", "usla"}:
        raise ValueError("Unsupported source egress node")
    prefix = "POLYMONITOR_EGRESS_" + node.upper()
    names = ("POLYMONITOR_EGRESS_IDENTITY", prefix + "_LISTEN", prefix + "_TARGET")
    values = [configured_value(name).strip() for name in names]
    for name, value in zip(names, values):
        if not value:
            raise ValueError(f"Missing {name}")
    identity, listen, target = values
    if target.startswith("-") or any(char.isspace() for char in target):
        raise ValueError(f"Invalid {prefix}_TARGET")
    return [
        "/usr/bin/ssh", "-N", "-T", "-i", identity,
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=12", "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
        "-o", "ProxyCommand=none", "-o", "ProxyJump=none", "-D", listen, target,
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=("ireland", "usla"), required=True)
    args = parser.parse_args()
    load_environment()
    try:
        command = ssh_argv(args.node)
    except ValueError as exc:
        parser.error(str(exc))
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
