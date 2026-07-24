#!/usr/bin/env python3
"""Build and apply conflict-aware polyData releases for the GCP serving host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_VERSION = 1
DEPLOYABLE_PREFIXES = (
    "agent/",
    "quant/",
    "scripts/",
    "telegram/",
    "deploy/systemd/",
)
DEPLOYABLE_FILES = {
    ".python-version",
    "pyproject.toml",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
APPROVED_OVERRIDES_PATH = Path("deploy/gcp/accepted-remote-overrides.json")


def _git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=text,
    )
    return result.stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"release target is not a regular file: {path}")
    return _sha256(path.read_bytes())


def _file_mode(path: Path) -> str | None:
    if not path.exists():
        return None
    return f"{stat.S_IMODE(path.stat().st_mode):04o}"


def _safe_relative_path(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuntimeError(f"unsafe release path: {raw!r}")
    return path.as_posix()


def _target_gcp_units(repo: Path, target: str) -> set[str]:
    content, _mode = _git_entry(repo, target, "deploy/systemd/polydata-gcp.target")
    if content is None:
        raise RuntimeError("target commit does not contain polydata-gcp.target")
    units = {"polydata-gcp.target", "polydata.target"}
    for raw_line in content.decode("utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(("Wants=", "Requires=")):
            units.update(line.split("=", 1)[1].split())
    return units


def _deployable(path: str, *, gcp_units: set[str]) -> bool:
    if path.startswith("deploy/systemd/"):
        return PurePosixPath(path).name in gcp_units
    runtime_prefixes = tuple(prefix for prefix in DEPLOYABLE_PREFIXES if prefix != "deploy/systemd/")
    return path in DEPLOYABLE_FILES or path.startswith(runtime_prefixes)


def _git_entry(repo: Path, ref: str, path: str) -> tuple[bytes | None, str | None]:
    tree = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", ref, "--", path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not tree:
        return None, None
    mode, object_type, _object_id, _name = tree.split(maxsplit=3)
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise RuntimeError(f"unsupported Git object for {path}: mode={mode} type={object_type}")
    content = _git(repo, "show", f"{ref}:{path}", text=False)
    return content, "0755" if mode == "100755" else "0644"


def _changed_paths(repo: Path, base: str, target: str) -> list[str]:
    output = _git(repo, "diff", "--name-only", "--no-renames", f"{base}..{target}")
    return sorted({_safe_relative_path(line) for line in str(output).splitlines() if line.strip()})


def _accepted_hashes(repo: Path, base: str, target: str, path: str) -> list[str | None]:
    commits = [base]
    commits.extend(
        line
        for line in str(
            _git(
                repo,
                "rev-list",
                "--ancestry-path",
                "--reverse",
                f"{base}..{target}",
                "--",
                path,
            )
        ).splitlines()
        if line
    )
    commits.append(target)
    hashes: set[str | None] = set()
    for commit in commits:
        content, _mode = _git_entry(repo, commit, path)
        hashes.add(_sha256(content) if content is not None else None)
    return sorted(hashes, key=lambda value: (value is not None, value or ""))


def _approved_remote_overrides(repo: Path, base: str) -> dict[str, str]:
    config_path = repo / APPROVED_OVERRIDES_PATH
    if not config_path.is_file():
        return {}
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    configured_base = str(payload.get("base_sha") or "")
    if configured_base != base:
        return {}
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, dict):
        raise RuntimeError(f"{APPROVED_OVERRIDES_PATH} paths must be an object")
    overrides: dict[str, str] = {}
    for raw_path, raw_hash in raw_paths.items():
        path = _safe_relative_path(str(raw_path))
        digest = str(raw_hash)
        if not SHA256_PATTERN.fullmatch(digest):
            raise RuntimeError(f"invalid approved SHA-256 for {path}")
        overrides[path] = digest
    return overrides


def build_release(repo: Path, base: str, target: str, output_dir: Path) -> dict[str, Any]:
    base = str(_git(repo, "rev-parse", f"{base}^{{commit}}")).strip()
    target = str(_git(repo, "rev-parse", f"{target}^{{commit}}")).strip()
    ancestor = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", base, target],
        check=False,
    )
    if ancestor.returncode != 0:
        raise RuntimeError(f"release base {base[:12]} is not an ancestor of target {target[:12]}")

    output_dir.mkdir(parents=True, exist_ok=False)
    payload_root = output_dir / "payload"
    payload_root.mkdir()
    entries: list[dict[str, Any]] = []
    ignored: list[str] = []
    approved_overrides = _approved_remote_overrides(repo, base)
    used_overrides: set[str] = set()
    gcp_units = _target_gcp_units(repo, target)

    for path in _changed_paths(repo, base, target):
        if not _deployable(path, gcp_units=gcp_units):
            ignored.append(path)
            continue
        before, before_mode = _git_entry(repo, base, path)
        after, after_mode = _git_entry(repo, target, path)
        if before is None and after is None:
            continue
        accepted_hashes = _accepted_hashes(repo, base, target, path)
        if path in approved_overrides:
            accepted_hashes.append(approved_overrides[path])
            accepted_hashes = sorted(set(accepted_hashes), key=lambda value: (value is not None, value or ""))
            used_overrides.add(path)
        entry = {
            "path": path,
            "action": "delete" if after is None else "upsert",
            "before_sha256": _sha256(before) if before is not None else None,
            "after_sha256": _sha256(after) if after is not None else None,
            "accepted_sha256": accepted_hashes,
            "before_mode": before_mode,
            "after_mode": after_mode,
        }
        entries.append(entry)
        if after is not None:
            destination = payload_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(after)
            os.chmod(destination, int(after_mode or "0644", 8))

    unused_overrides = sorted(set(approved_overrides) - used_overrides)
    if unused_overrides:
        raise RuntimeError(f"approved remote overrides do not match changed deployable paths: {unused_overrides}")

    manifest = {
        "version": MANIFEST_VERSION,
        "base_sha": base,
        "target_sha": target,
        "entries": entries,
        "ignored_paths": ignored,
        "approved_remote_overrides": sorted(used_overrides),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with tarfile.open(output_dir / "payload.tar.gz", "w:gz") as archive:
        for entry in entries:
            if entry["action"] == "upsert":
                archive.add(payload_root / entry["path"], arcname=entry["path"], recursive=False)
    shutil.rmtree(payload_root)
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != MANIFEST_VERSION:
        raise RuntimeError(f"unsupported manifest version: {manifest.get('version')!r}")
    if not isinstance(manifest.get("entries"), list):
        raise RuntimeError("manifest entries must be a list")
    for entry in manifest["entries"]:
        entry["path"] = _safe_relative_path(str(entry["path"]))
        if entry.get("action") not in {"upsert", "delete"}:
            raise RuntimeError(f"unsupported action for {entry['path']}: {entry.get('action')!r}")
    return manifest


def preflight(root: Path, manifest: dict[str, Any]) -> list[dict[str, str | None]]:
    conflicts: list[dict[str, str | None]] = []
    for entry in manifest["entries"]:
        destination = root / entry["path"]
        current_sha = _file_sha256(destination)
        current_mode = _file_mode(destination)
        expected_hashes = set(entry.get("accepted_sha256") or [])
        expected_hashes.update({entry.get("before_sha256"), entry.get("after_sha256")})
        # Runtime umasks commonly add group-write permission (0644 -> 0664).
        # Content is the conflict boundary; apply still normalizes the final
        # mode to the mode recorded by Git.
        if current_sha not in expected_hashes:
            conflicts.append(
                {
                    "path": entry["path"],
                    "current_sha256": current_sha,
                    "current_mode": current_mode,
                    "expected_before_sha256": entry.get("before_sha256"),
                    "expected_before_mode": entry.get("before_mode"),
                    "expected_after_sha256": entry.get("after_sha256"),
                    "expected_after_mode": entry.get("after_mode"),
                }
            )
    return conflicts


def _print_conflicts(conflicts: list[dict[str, str | None]]) -> None:
    for conflict in conflicts:
        print(
            "CONFLICT "
            f"{conflict['path']} "
            f"current={str(conflict['current_sha256'])[:12]}/{conflict['current_mode']} "
            f"before={str(conflict['expected_before_sha256'])[:12]}/{conflict['expected_before_mode']} "
            f"after={str(conflict['expected_after_sha256'])[:12]}/{conflict['expected_after_mode']}"
        )


def _extract_payload(archive_path: Path, destination: Path, manifest: dict[str, Any]) -> None:
    expected = {entry["path"] for entry in manifest["entries"] if entry["action"] == "upsert"}
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        actual = {_safe_relative_path(member.name) for member in members}
        if actual != expected:
            raise RuntimeError("payload members do not match manifest")
        for member in members:
            if not member.isfile():
                raise RuntimeError(f"payload contains non-file member: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"payload member cannot be read: {member.name}")
            target = destination / _safe_relative_path(member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            os.chmod(target, stat.S_IMODE(member.mode))


def apply_release(
    root: Path,
    manifest_path: Path,
    payload_path: Path,
    backup_root: Path,
) -> Path:
    manifest = load_manifest(manifest_path)
    conflicts = preflight(root, manifest)
    if conflicts:
        _print_conflicts(conflicts)
        raise RuntimeError(f"release blocked by {len(conflicts)} conflicting remote files")

    release_id = str(manifest["target_sha"])
    backup_dir = backup_root / release_id
    if backup_dir.exists():
        raise RuntimeError(f"backup already exists for release {release_id}")
    backup_dir.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="polydata-release-") as temporary:
        payload_root = Path(temporary)
        _extract_payload(payload_path, payload_root, manifest)
        receipt_entries: list[dict[str, Any]] = []
        for entry in manifest["entries"]:
            relative = entry["path"]
            destination = root / relative
            existed = destination.exists()
            previous_mode = _file_mode(destination)
            if existed:
                backup_path = backup_dir / "files" / relative
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_path)
            receipt_entries.append(
                {
                    "path": relative,
                    "existed": existed,
                    "previous_mode": previous_mode,
                }
            )

            if entry["action"] == "delete":
                if destination.exists():
                    destination.unlink()
                continue

            source = payload_root / relative
            if _file_sha256(source) != entry["after_sha256"]:
                raise RuntimeError(f"payload hash mismatch for {relative}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_destination = destination.with_name(f".{destination.name}.polydata-new")
            shutil.copyfile(source, temporary_destination)
            os.chmod(temporary_destination, int(entry["after_mode"], 8))
            temporary_destination.replace(destination)

    receipt = {
        "version": MANIFEST_VERSION,
        "base_sha": manifest["base_sha"],
        "target_sha": manifest["target_sha"],
        "entries": receipt_entries,
    }
    receipt_path = backup_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt_path


def rollback_release(root: Path, receipt_path: Path) -> None:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    backup_dir = receipt_path.parent
    for entry in reversed(receipt["entries"]):
        destination = root / _safe_relative_path(entry["path"])
        if entry["existed"]:
            backup_path = backup_dir / "files" / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_destination = destination.with_name(f".{destination.name}.polydata-rollback")
            shutil.copyfile(backup_path, temporary_destination)
            os.chmod(temporary_destination, int(entry["previous_mode"], 8))
            temporary_destination.replace(destination)
        elif destination.exists():
            destination.unlink()


def _command_build(args: argparse.Namespace) -> int:
    manifest = build_release(args.repo.resolve(), args.base, args.target, args.output.resolve())
    print(
        f"release-built base={manifest['base_sha'][:12]} target={manifest['target_sha'][:12]} "
        f"entries={len(manifest['entries'])} ignored={len(manifest['ignored_paths'])}"
    )
    return 0


def _command_preflight(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest.resolve())
    conflicts = preflight(args.root.resolve(), manifest)
    if conflicts:
        _print_conflicts(conflicts)
        return 2
    print(f"release-preflight: ok entries={len(manifest['entries'])}")
    return 0


def _command_apply(args: argparse.Namespace) -> int:
    receipt = apply_release(
        args.root.resolve(),
        args.manifest.resolve(),
        args.payload.resolve(),
        args.backup_root.resolve(),
    )
    print(f"release-applied receipt={receipt}")
    return 0


def _command_rollback(args: argparse.Namespace) -> int:
    rollback_release(args.root.resolve(), args.receipt.resolve())
    print(f"release-rolled-back receipt={args.receipt.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build a release payload from two Git revisions")
    build.add_argument("--repo", type=Path, default=Path.cwd())
    build.add_argument("--base", required=True)
    build.add_argument("--target", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(handler=_command_build)

    preflight_parser = commands.add_parser("preflight", help="check the remote tree for conflicts")
    preflight_parser.add_argument("--root", type=Path, required=True)
    preflight_parser.add_argument("--manifest", type=Path, required=True)
    preflight_parser.set_defaults(handler=_command_preflight)

    apply_parser = commands.add_parser("apply", help="apply a preflighted release with backups")
    apply_parser.add_argument("--root", type=Path, required=True)
    apply_parser.add_argument("--manifest", type=Path, required=True)
    apply_parser.add_argument("--payload", type=Path, required=True)
    apply_parser.add_argument("--backup-root", type=Path, required=True)
    apply_parser.set_defaults(handler=_command_apply)

    rollback_parser = commands.add_parser("rollback", help="restore files from an apply receipt")
    rollback_parser.add_argument("--root", type=Path, required=True)
    rollback_parser.add_argument("--receipt", type=Path, required=True)
    rollback_parser.set_defaults(handler=_command_rollback)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except (OSError, RuntimeError, subprocess.CalledProcessError, tarfile.TarError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
