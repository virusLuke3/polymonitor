"""Render bounded snapshot transport from the existing API registry."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import argparse
import ipaddress
import json
import re
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.runtime_panels import RUNTIME_PANEL_MODULES
from runtime.environment import configured_value


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


def render_upstreams(bulk: list[str], interactive: str, panel: str, book: str | None = None) -> str:
    def address(value: str) -> str:
        host, port = value.split(":")
        if not ipaddress.ip_address(host).is_loopback or not 1 <= int(port) <= 65535:
            raise ValueError("Website upstream must be a loopback socket")
        return f"{host}:{int(port)}"
    if not isinstance(bulk, list) or not 1 <= len(bulk) <= 4:
        raise ValueError("Expected one to four website bulk connections")
    template = Path(__file__).resolve().parents[2] / "deploy/nginx/polydata-relay-upstreams.conf.example"
    # Two slow source responses do not mean both loopback SSH listeners died.
    # Still retry a failed request on the other connection, without temporarily
    # excluding every peer and turning unrelated reads into immediate 502s.
    rendered = (template.read_text().replace("__POLYMONITOR_WEB_API_UPSTREAM_SERVERS__",
            "\n    ".join(f"server {address(item)}{' backup' if index else ''} max_fails=0;" for index, item in enumerate(bulk)))
            .replace("__POLYMONITOR_WEB_INTERACTIVE_UPSTREAM_SERVER__",
                     f"server {address(interactive)};")
            + "\nupstream polymonitor_panel_api {\n"
            + f"    server {address(panel)} max_fails=0;\n"
            + f"    server {address(bulk[-1])} backup max_fails=0;\n"
            + "    keepalive 4;\n    keepalive_timeout 15s;\n    keepalive_requests 100;\n}\n")
    if book:
        rendered += "\nupstream polymonitor_book_api {\n    server " + address(book) + ";\n}\n"
    return rendered


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upstreams-output", type=Path)
    args = parser.parse_args()
    args.output.write_text(render())
    if args.upstreams_output:
        args.upstreams_output.write_text(render_upstreams(
            json.loads(configured_value("POLYMONITOR_WEB_API_UPSTREAMS_JSON")),
            configured_value("POLYMONITOR_WEB_INTERACTIVE_UPSTREAM"),
            configured_value("POLYMONITOR_WEB_PANEL_UPSTREAM"),
            configured_value("POLYMONITOR_WEB_LOB_UPSTREAM") or None))
