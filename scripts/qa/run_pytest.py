#!/usr/bin/env python3
"""Run the tracked test suite while exposing the exact pre-CI quarantine."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _quarantined_node_ids(path: Path) -> list[str]:
    return [
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-quarantined", action="store_true")
    parser.add_argument("pytest_args", nargs="*")
    args = parser.parse_args()

    command = [sys.executable, "-m", "pytest", "-q"]
    quarantine_path = root / "scripts" / "qa" / "pytest-quarantine.txt"
    quarantined = [] if args.include_quarantined else _quarantined_node_ids(quarantine_path)
    for node_id in quarantined:
        command.append(f"--deselect={node_id}")
    command.extend(args.pytest_args)

    if quarantined:
        print(f"pytest-quarantine: deselecting {len(quarantined)} known pre-CI failures", flush=True)
    return subprocess.call(command, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
