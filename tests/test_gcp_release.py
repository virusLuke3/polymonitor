"""Backend releases must run without files left over on the serving host."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.deploy import gcp_release as release


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo):
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Release Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
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
        "scripts/db/__init__.py", "scripts/db/db.py", "scripts/db/trade_v2.py",
        "scripts/market/market_serving_identity.py", "scripts/trade/orderfilled_raw.py",
        "scripts/oracle/settlement_parser.py", "scripts/weather/temperature_bins.py",
        "scripts/f1/runtime_feed.py", "scripts/jin10/flash_client.py",
        "scripts/runtime/worldcup_seed_common.py", "scripts/data/live_video_sources.json",
    ):
        assert release._deployable(path, gcp_units=set()), path
    for path in (
        "scripts/db/archive/backfill_trades_v2.py", "scripts/db/migrate_sqlite_to_mysql.py",
        "scripts/trade/clickhouse_orderfilled_writer.py", "scripts/trade/trade_decoder.py",
        "scripts/clickhouse/build_position_snapshots.py", "scripts/deploy/gcp_release.py",
        "scripts/qa/check_systemd_units.py", "webpage/src/App.tsx",
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
    subprocess.run([sys.executable, "-B", "-c", """
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
"""], cwd=remote, env=env, check=True, timeout=60)
