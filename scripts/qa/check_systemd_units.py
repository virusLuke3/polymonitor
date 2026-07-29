#!/usr/bin/env python3
"""Validate repository-owned systemd dependency and executable references."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable


DEPENDENCY_KEYS = {"Requires", "Wants"}
MODULE_PATTERN = re.compile(r"(?:^|\s)-m\s+([A-Za-z_][A-Za-z0-9_.]*)")
SCRIPT_PATTERN = re.compile(r"\b((?:scripts)/[A-Za-z0-9_./-]+\.(?:py|sh))\b")


def _referenced_units(path: Path) -> Iterable[str]:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in DEPENDENCY_KEYS:
            yield from value.split()


def _template_name(unit: str) -> str:
    if "@" not in unit:
        return unit
    prefix, suffix = unit.split("@", 1)
    if suffix == ".service":
        return unit
    if suffix.endswith(".service"):
        return f"{prefix}@.service"
    return unit


def _module_exists(root: Path, module: str) -> bool:
    for import_root in (root, root / "scripts"):
        module_path = import_root.joinpath(*module.split("."))
        if module_path.with_suffix(".py").is_file() or (module_path / "__init__.py").is_file():
            return True
    return False


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    unit_dir = root / "deploy" / "systemd"

    for target in sorted(unit_dir.glob("*.target")):
        for unit in _referenced_units(target):
            if not unit.startswith("polydata-"):
                continue
            expected = unit_dir / _template_name(unit)
            if not expected.is_file():
                errors.append(f"{target.relative_to(root)} references missing unit {unit}")

    for service in sorted(unit_dir.glob("*.service")):
        content = service.read_text(encoding="utf-8")
        for relative_path in SCRIPT_PATTERN.findall(content):
            if not (root / relative_path).is_file():
                errors.append(f"{service.relative_to(root)} references missing executable {relative_path}")
        for module in MODULE_PATTERN.findall(content):
            if not _module_exists(root, module):
                errors.append(f"{service.relative_to(root)} references missing Python module {module}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    unit_dir = root / "deploy" / "systemd"
    print(
        "systemd-contracts: ok "
        f"services={len(list(unit_dir.glob('*.service')))} "
        f"timers={len(list(unit_dir.glob('*.timer')))} "
        f"targets={len(list(unit_dir.glob('*.target')))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
