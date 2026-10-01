"""Backend releases must run without files left over on the serving host."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import json
import pytest

from scripts.deploy import gcp_release as release


@pytest.mark.parametrize("failure", ["hash", "stage", "write", "interrupt", "crash"])
def test_release_failure_restores_files_or_leaves_complete_recovery(tmp_path, monkeypatch, failure):
    import io
    import tarfile

    root, backups = tmp_path / "root", tmp_path / "backups"
    root.mkdir()
    entries = []
    payload = tmp_path / "payload.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        for name in ("first.py", "second.py"):
            (root / name).write_bytes(b"old")
            item = tarfile.TarInfo(name)
            item.size, item.mode = 3, 0o644
            archive.addfile(item, io.BytesIO(b"new"))
            entries.append(
                {
                    "path": name,
                    "action": "upsert",
                    "before_sha256": release._sha256(b"old"),
                    "after_sha256": release._sha256(b"new"),
                    "after_mode": "0644",
                }
            )
    if failure == "hash":
        entries[-1]["after_sha256"] = "invalid"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"version": release.MANIFEST_VERSION, "base_sha": "old", "target_sha": "new", "entries": entries})
    )
    receipt = backups / "new" / "receipt.json"
    if failure == "crash":
        code = """
import os, sys
from pathlib import Path
from scripts.deploy.gcp_release import apply_release
replace = Path.replace
def crash(source, target):
    if source.name == '.second.py.polydata-new':
        os._exit(9)
    return replace(source, target)
Path.replace = crash
apply_release(*(Path(value) for value in sys.argv[1:]))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(root), str(manifest), str(payload), str(backups)]
        )
        assert result.returncode == 9
        assert (root / "first.py").read_bytes() == b"new"
        release.rollback_release(root, receipt)
    else:
        replace = Path.replace

        def fail(source, target):
            if source.name == ".second.py.polydata-new":
                assert len(json.loads(receipt.read_text())["entries"]) == 2
                raise KeyboardInterrupt() if failure == "interrupt" else OSError("injected failure")
            return replace(source, target)

        if failure == "stage":
            copyfile = shutil.copyfile

            def no_space(source, destination, **kwargs):
                if Path(destination).name == ".second.py.polydata-new":
                    assert (root / "first.py").read_bytes() == b"old"
                    raise OSError("injected disk full")
                return copyfile(source, destination, **kwargs)

            monkeypatch.setattr(shutil, "copyfile", no_space)
        elif failure != "hash":
            monkeypatch.setattr(Path, "replace", fail)
        with pytest.raises((RuntimeError, OSError, KeyboardInterrupt)):
            release.apply_release(root, manifest, payload, backups)
    assert all((root / name).read_bytes() == b"old" for name in ("first.py", "second.py"))
    assert not list(root.glob(".*.polydata-*"))
    if failure == "hash":
        assert not backups.exists()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo):
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "fixture",
    )
    return git(repo, "rev-parse", "HEAD")


def test_release_repairs_missing_dependencies_and_preserves_remote_edits(tmp_path):
    repo, remote = tmp_path / "repo", tmp_path / "remote"
    repo.mkdir()
    remote.mkdir()
    git(repo, "init", "-q")
    files = {
        "deploy/systemd/polydata-gcp.target": "[Unit]\nWants=polydata-api.service polydata-retired.timer\n",
        "deploy/systemd/polydata-api.service": "[Service]\nExecStart=python -m api.app\n",
        "deploy/systemd/polydata-market-sync.service": "collector",
        "deploy/systemd/polydata-retired.timer": "[Timer]\nUnit=polydata-retired.service\n",
        "deploy/systemd/polydata-retired.service": "[Service]\nExecStart=retired\n",
        "scripts/api/app.py": "old API",
        "scripts/db/db.py": "unchanged database dependency",
        "scripts/db/trade_v2.py": "unchanged trade reader",
        "scripts/runtime/retired.py": "retired consumer",
        "quant/api/read_api.py": "retired Quant API",
        "design-qa.md": "old local report",
        "scripts/data/live_video_sources.json": "{}",
        "webpage/src/App.tsx": "frontend",
    }
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    base = commit(repo)
    (repo / "scripts/api/app.py").write_text("new API")
    (repo / "scripts/runtime/retired.py").unlink()
    (repo / "quant/api/read_api.py").unlink()
    (repo / "design-qa.md").unlink()
    (repo / "deploy/systemd/polydata-gcp.target").write_text("[Unit]\nWants=polydata-api.service\n")
    for unit in ("polydata-retired.service", "polydata-retired.timer"):
        (repo / "deploy/systemd" / unit).unlink()
    target = commit(repo)
    (repo / "scripts/api/app.py").write_text("uncommitted edit must not ship")
    output = tmp_path / "release"
    manifest = release.build_release(repo, base, target, output)
    assert not manifest["ignored_paths"]
    paths = {entry["path"] for entry in manifest["entries"]}
    assert {"scripts/db/db.py", "scripts/db/trade_v2.py", "scripts/data/live_video_sources.json"} <= paths
    assert "deploy/systemd/polydata-market-sync.service" not in paths
    assert "webpage/src/App.tsx" not in paths
    assert "design-qa.md" in manifest["external_paths"]
    assert "quant/api/read_api.py" in paths
    assert {"deploy/systemd/polydata-retired.service", "deploy/systemd/polydata-retired.timer"} <= paths
    for name in ("scripts/api/app.py", "scripts/runtime/retired.py", "deploy/systemd/polydata-retired.timer"):
        path = remote / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[name])
    assert release.preflight(remote, manifest) == []
    receipt = release.apply_release(remote, output / "manifest.json", output / "payload.tar.gz", tmp_path / "backups")
    assert (remote / "scripts/api/app.py").read_text() == "new API"
    assert (remote / "scripts/db/trade_v2.py").read_text() == files["scripts/db/trade_v2.py"]
    assert not (remote / "scripts/runtime/retired.py").exists()
    assert not (remote / "deploy/systemd/polydata-retired.timer").exists()
    (remote / "scripts/db/db.py").write_text("unknown remote hotfix")
    assert [entry["path"] for entry in release.preflight(remote, manifest)] == ["scripts/db/db.py"]
    release.rollback_release(remote, receipt)
    assert (remote / "scripts/api/app.py").read_text() == "old API"
    assert (remote / "scripts/runtime/retired.py").exists()
    assert (remote / "deploy/systemd/polydata-retired.timer").exists()
    assert not (remote / "scripts/db/db.py").exists()


def test_release_scope_keeps_consumer_packages_and_excludes_tools():
    for path in (
        "scripts/db/__init__.py",
        "scripts/db/db.py",
        "scripts/db/trade_v2.py",
        "scripts/market/market_serving_identity.py",
        "scripts/trade/orderfilled_raw.py",
        "scripts/oracle/settlement_parser.py",
        "scripts/weather/temperature_bins.py",
        "scripts/f1/runtime_feed.py",
        "scripts/jin10/flash_client.py",
        "scripts/runtime/worldcup_seed_common.py",
        "scripts/data/live_video_sources.json",
    ):
        assert release._deployable(path, gcp_units=set()), path
    for path in (
        "scripts/db/archive/backfill_trades_v2.py",
        "scripts/db/migrate_sqlite_to_mysql.py",
        "scripts/trade/clickhouse_orderfilled_writer.py",
        "scripts/trade/trade_decoder.py",
        "scripts/clickhouse/build_position_snapshots.py",
        "scripts/deploy/gcp_release.py",
        "scripts/qa/check_systemd_units.py",
        "webpage/src/App.tsx",
    ):
        assert not release._deployable(path, gcp_units=set()), path
        assert release._externally_owned(path), path
    assert not release._deployable("quant/api/read_api.py", gcp_units=set())
    assert not release._externally_owned("scripts/unknown_runtime/helper.py")


def test_packaged_api_starts_without_the_source_checkout(tmp_path):
    root = Path(__file__).resolve().parents[1]
    repo, remote = tmp_path / "repo", tmp_path / "remote"
    repo.mkdir()
    git(repo, "init", "-q")
    paths = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    for name in set(paths):
        source = root / name
        if source.is_file() and (release._deployable(name, gcp_units=set()) or name.startswith("deploy/systemd/")):
            destination = repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    target = commit(repo)
    output = tmp_path / "release"
    manifest = release.build_release(repo, target, target, output)
    assert manifest["entries"] and not manifest["ignored_paths"]
    release.apply_release(remote, output / "manifest.json", output / "payload.tar.gz", tmp_path / "backups")
    env = {key: os.environ[key] for key in ("PATH", "HOME", "SYSTEMROOT") if key in os.environ}
    env.update(POLYDATA_DISABLE_DOTENV="1", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=f"{remote}/scripts:{remote}")
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
import importlib, json, pathlib, socket
def no_network(*args, **kwargs):
    raise AssertionError('startup attempted network access')
socket.socket.connect = no_network
from api.app import create_app
app = create_app(connection_factory=no_network)
try:
    assert app.test_client().get('/health').status_code == 200
    for path in pathlib.Path('scripts/runtime').glob('*.py'):
        importlib.import_module('runtime.' + path.stem)
    import telegram.bot.poller, telegram.topics.publisher, agent.gateway.app
    from db.trade_v2 import get_trade_read_source, uint256_storage_to_text
    assert get_trade_read_source() == 'trades_v2_read'
    assert uint256_storage_to_text((7).to_bytes(32, 'big')) == '7'
    assert json.loads(pathlib.Path('scripts/data/live_video_sources.json').read_text())
    assert pathlib.Path(importlib.import_module('db.db').__file__).is_relative_to(pathlib.Path.cwd())
finally:
    app.extensions['polydata_runtime'].close()
""",
        ],
        cwd=remote,
        env=env,
        check=True,
        timeout=60,
    )


def test_unit_retirement_and_rollback_restore_installed_state(tmp_path, monkeypatch):
    import json

    root, units = tmp_path / "root", tmp_path / "units"
    (root / "deploy/systemd").mkdir(parents=True)
    units.mkdir()
    retired = "polydata-retired.timer"
    foreign = units / "market-data-live.service"
    foreign.write_text("foreign service")
    (units / retired).write_text("old timer")
    manifest = {
        "version": release.MANIFEST_VERSION,
        "entries": [{"path": "deploy/systemd/" + retired, "action": "delete"}],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"entries": []}))
    calls = []

    def systemctl(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="enabled\n" if args[0] == "is-enabled" else "active\n")

    monkeypatch.setattr(release, "_systemctl", systemctl)
    release.sync_systemd_units(root, manifest_path, receipt, units)
    assert not (units / retired).exists()
    assert ("stop", retired) in calls
    assert ("disable", retired) in calls
    release.rollback_release(root, receipt)
    assert (units / retired).read_text() == "old timer"
    assert ("enable", retired) in calls
    assert ("restart", retired) in calls
    assert foreign.read_text() == "foreign service"


def test_unit_rollback_stops_previously_inactive_service(tmp_path, monkeypatch):
    installed = tmp_path / "polydata-api.service"
    installed.write_text("new unit")
    calls = []
    monkeypatch.setattr(release, "_systemctl", lambda *args, **kwargs: calls.append(args))
    release._restore_systemd_units(
        [
            {
                "name": installed.name,
                "path": str(installed),
                "content": "old unit",
                "mode": 0o640,
                "active": False,
                "enabled": False,
            }
        ]
    )
    assert installed.read_text() == "old unit"
    assert installed.stat().st_mode & 0o777 == 0o640
    assert ("stop", installed.name) in calls
    assert ("restart", installed.name) not in calls


def test_release_readiness_rejects_successful_http_with_stale_or_unavailable_data():
    from datetime import datetime, timezone
    import pytest

    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    for payload in (
        {"items": [], "status": "stale", "generatedAt": now.isoformat()},
        {"items": [], "status": "empty", "generatedAt": "2026-09-28T12:00:00Z"},
        {"items": [], "status": "unavailable", "generatedAt": now.isoformat()},
    ):
        with pytest.raises(RuntimeError):
            release.validate_readiness_payload("whales", payload, now=now)
    release.validate_readiness_payload(
        "flow", {"items": [], "status": "empty", "generatedAt": now.isoformat()}, now=now
    )
    with pytest.raises(RuntimeError):
        release.validate_readiness_payload("health", {"status": "degraded", "database": True, "redis": False}, now=now)


def test_content_release_scope_rejects_unreviewed_empty_or_stale_data():
    from datetime import datetime, timezone
    import copy
    import pytest

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    good = {
        "scope": "global",
        "status": "partial",
        "count": 1,
        "lastSuccessfulCheckAt": now.isoformat(),
        "sources": [
            {
                "source_id": "global-voices",
                "enabled": True,
                "probe_status": "passed",
                "policy_checked_at": now.isoformat(),
                "display_title_allowed": True,
            }
        ],
        "items": [
            {
                "sourceId": "global-voices",
                "display_allowed": True,
                "title": "Fixture article",
                "url": "https://globalvoices.org/fixture/",
                "author": "Fixture author",
                "licenseUrl": "https://creativecommons.org/licenses/by/3.0/",
            }
        ],
    }
    release.validate_readiness_payload("content", good, now=now)
    for change in (
        {"scope": "market"},
        {"items": []},
        {"lastSuccessfulCheckAt": "2026-09-28T00:00:00Z"},
        {"status": "unavailable"},
    ):
        with pytest.raises(RuntimeError):
            release.validate_readiness_payload("content", {**good, **change}, now=now)
    bad = copy.deepcopy(good)
    bad["items"][0]["display_allowed"] = False
    with pytest.raises(RuntimeError):
        release.validate_readiness_payload("content", bad, now=now)
    assert release.build_parser().parse_args(["verify"]).scope == "default"


def test_map_release_checks_acquisition_time_and_preserves_partial_coverage():
    from datetime import datetime, timezone
    import pytest

    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    source = {"key": "nws", "status": "partial", "lastSuccessAt": now.isoformat(), "errorCode": None}
    payload = {"schemaVersion": "natural-hazards-map.v1", "events": [], "sources": [source], "generatedAt": now.isoformat()}
    release.validate_readiness_payload("hazard-nws", payload, now=now)
    for change in (
        {"status": "degraded"}, {"lastSuccessAt": "2026-09-30T12:00:00Z"},
        {"lastSuccessAt": None}, {"errorCode": "nws-provider-deadline-exceeded"},
    ):
        with pytest.raises(RuntimeError):
            release.validate_readiness_payload("hazard-nws", {**payload, "sources": [{**source, **change}]}, now=now)
    with pytest.raises(RuntimeError):
        release.validate_readiness_payload("hazard-usgs", payload, now=now)


def test_map_release_rejects_unavailable_or_inconsistent_aviation():
    from datetime import datetime, timezone
    import pytest

    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    payload = {"schemaVersion": "aviation-viewport.v1", "aircraft": [], "aircraftCount": 0, "status": "empty", "generatedAt": now.isoformat()}
    release.validate_readiness_payload("aviation", payload, now=now)
    release.validate_readiness_payload("aviation", {**payload, "status": "partial"}, now=now)
    for change in ({"status": "unavailable"}, {"schemaVersion": "unknown"}, {"aircraftCount": 1}, {"generatedAt": "2026-09-30T12:00:00Z"}):
        with pytest.raises(RuntimeError):
            release.validate_readiness_payload("aviation", {**payload, **change}, now=now)
    assert release.build_parser().parse_args(["verify", "--scope", "world-event-map"]).scope == "world-event-map"
