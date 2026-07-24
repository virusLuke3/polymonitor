#!/usr/bin/env python3
"""Fail when tracked files contain high-confidence credentials or private paths."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Iterable


SECRET_PATTERNS = {
    "private-key-header": re.compile(
        "-----BEGIN " + r"(?:(?:RSA|EC|OPENSSH|DSA) )?PRIVATE KEY-----"
    ),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,})\b"),
    "openai-style-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "telegram-bot-token": re.compile(r"\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b"),
    "credential-url": re.compile(r"https?://[^/@\s]+:[^/@\s]+@"),
}
HOME_PATH_PATTERN = re.compile(r"/(?:home|Users)/([A-Za-z0-9._-]+)(?:/|$)")
REMOTE_HOME_PATTERN = re.compile(r"\b([A-Za-z0-9._-]+)@[A-Za-z0-9._-]+:~/")
GENERIC_HOME_NAMES = {"example", "runner", "user", "username"}


def _tracked_paths(root: Path) -> Iterable[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    for raw_path in result.stdout.split(b"\0"):
        if raw_path:
            yield root / raw_path.decode("utf-8", errors="surrogateescape")


def _text_lines(path: Path) -> Iterable[tuple[int, str]]:
    try:
        content = path.read_bytes()
    except (FileNotFoundError, OSError):
        return
    if b"\0" in content:
        return
    text = content.decode("utf-8", errors="replace")
    yield from enumerate(text.splitlines(), start=1)


def scan(root: Path) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path in _tracked_paths(root):
        for line_number, line in _text_lines(path):
            label = next((name for name, pattern in SECRET_PATTERNS.items() if pattern.search(line)), "")
            if label:
                findings.append((str(path.relative_to(root)), line_number, label))
                continue
            home_match = HOME_PATH_PATTERN.search(line)
            if home_match and home_match.group(1).lower() not in GENERIC_HOME_NAMES:
                findings.append((str(path.relative_to(root)), line_number, "personal-home-path"))
                continue
            remote_match = REMOTE_HOME_PATTERN.search(line)
            if remote_match and remote_match.group(1).lower() not in GENERIC_HOME_NAMES:
                findings.append((str(path.relative_to(root)), line_number, "personal-remote-path"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan(root)
    if findings:
        for path, line_number, label in findings:
            print(f"ERROR: {path}:{line_number}: {label} (value redacted)")
        return 1
    print("tracked-secret-scan: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
