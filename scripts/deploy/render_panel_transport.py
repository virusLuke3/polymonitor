"""Render bounded snapshot transport from the existing API registry."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import argparse
import re
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.runtime_panels import RUNTIME_PANEL_MODULES


def public_snapshot_pattern() -> str:
    routes = {panel.route for panel in RUNTIME_PANEL_MODULES}
    routes.update(f"/runtime/agent/market-wide-insights/{lens}" for lens in ("overview", "special", "trend"))
    groups: dict[str, list[str]] = defaultdict(list)
    for route in sorted(routes):
        family, name = route.removeprefix("/runtime/").split("/", 1)
        groups[family].append(re.escape(name))
    return "|".join(f"{re.escape(family)}/({'|'.join(names)})" for family, names in groups.items())


def render() -> str:
    template = Path(__file__).resolve().parents[2] / "deploy/nginx/polymonitor-panel-transport.conf"
    return template.read_text().replace("__PUBLIC_PANEL_SNAPSHOT_PATHS__", public_snapshot_pattern())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(render())
