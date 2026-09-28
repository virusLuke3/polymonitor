from __future__ import annotations

import os
import unittest
from unittest.mock import patch


from api import config as api_config


class ApiConfigKeyAliasTestCase(unittest.TestCase):
    def load_settings_with_env(self, env: dict[str, str]) -> api_config.ApiSettings:
        with patch.dict(os.environ, env, clear=True), patch.object(api_config, "load_environment", lambda: None):
            return api_config.load_api_settings()

    def test_the_odds_api_key_accepts_lowercase_local_alias(self):
        settings = self.load_settings_with_env({"the_odds_api_key": "fixture-odds-key"})

        self.assertEqual("fixture-odds-key", settings.the_odds_api_key)

    def test_the_odds_api_key_accepts_short_local_alias(self):
        settings = self.load_settings_with_env({"odds_api_key": "fixture-short-odds-key"})

        self.assertEqual("fixture-short-odds-key", settings.the_odds_api_key)

    def test_the_odds_api_key_accepts_second_free_key_alias(self):
        settings = self.load_settings_with_env({"odds_api_key2": "fixture-second-free-key"})

        self.assertEqual("fixture-second-free-key", settings.the_odds_api_key)

    def test_the_odds_api_key_accepts_canonical_second_key_alias(self):
        settings = self.load_settings_with_env({"POLYDATA_THE_ODDS_API_KEY2": "fixture-canonical-second-key"})

        self.assertEqual("fixture-canonical-second-key", settings.the_odds_api_key)

    def test_canonical_the_odds_api_key_overrides_aliases(self):
        settings = self.load_settings_with_env(
            {
                "POLYDATA_THE_ODDS_API_KEY": "canonical-odds-key",
                "the_odds_api_key": "lowercase-odds-key",
                "odds_api_key": "short-odds-key",
                "THE_ODDS_API_KEY": "legacy-odds-key",
            }
        )

        self.assertEqual("canonical-odds-key", settings.the_odds_api_key)

    def test_second_free_key_overrides_exhausted_primary_key_when_present(self):
        settings = self.load_settings_with_env(
            {
                "POLYDATA_THE_ODDS_API_KEY": "exhausted-primary-key",
                "odds_api_key2": "fresh-second-free-key",
            }
        )

        self.assertEqual("fresh-second-free-key", settings.the_odds_api_key)


def test_application_factory_owns_configuration_caches_and_connections(tmp_path):
    from dataclasses import replace
    from api.app import create_app
    from api.runtime import ServiceRuntime

    settings = replace(api_config.load_api_settings(), snapshot_sqlite_path=str(tmp_path / "snapshots.sqlite3"))

    def no_database(*args, **kwargs):
        raise AssertionError("Constructing an app must not contact the database")

    with patch.object(ServiceRuntime, "start", side_effect=AssertionError("Unexpected prewarm")):
        first = create_app(replace(settings, port=18501), connection_factory=no_database)
        second = create_app(replace(settings, port=18502), connection_factory=no_database)
    assert first is not second
    a, b = (app.extensions["polydata_runtime"] for app in (first, second))
    assert a.bootstrap_cache is not b.bootstrap_cache
    a._dashboard_cache["value"] = {"only": "first"}
    a.global_weather_map.runtime_state["_weather_test"] = True
    assert b._dashboard_cache["value"] is None
    assert "_weather_test" not in b.global_weather_map.runtime_state
    assert first.config["POLYDATA_API_PORT"] == 18501
    assert second.config["POLYDATA_API_PORT"] == 18502
    assert a.api_db_context["get_connection"] is no_database
    assert first.test_client().get("/health").status_code == 200
    assert second.test_client().get("/health").status_code == 200
    from api.services import clickhouse_orderfilled_service
    with patch.object(clickhouse_orderfilled_service, "get_price_series", return_value=[{"timestamp": "t"}]) as read_prices:
        assert a.get_trade_derived_market_price_series(9) == [{"timestamp": "t"}]
        assert callable(read_prices.call_args.args[0]["query_all"])
    assert not list(tmp_path.iterdir())
    a.close()
    b.close()


def test_public_health_redacts_connection_details_and_reports_redis_failure():
    from flask import Flask
    from unittest.mock import Mock
    from api.routes.system import SystemRouteDependencies, create_system_blueprint

    redis = Mock()
    redis.ping.return_value = True
    app = Flask(__name__)
    app.register_blueprint(create_system_blueprint(SystemRouteDependencies(
        authenticate_request=Mock(), build_system_health_payload=Mock(), build_seed_health_payload=Mock(),
        describe_db_target=lambda: "postgres:private-user@private-host/private-db",
        get_redis_client=lambda: redis,
    )))
    client = app.test_client()
    assert client.get("/health").get_json() == {"status": "ok", "database": True, "redis": True}
    redis.ping.side_effect = ConnectionError("private connection details")
    assert client.get("/health").get_json() == {"status": "degraded", "database": True, "redis": False}


def test_environment_precedence_and_opt_out(tmp_path, monkeypatch):
    from runtime.environment import load_environment

    (tmp_path / "scripts").mkdir()
    (tmp_path / ".env").write_text("CONFIG_SHARED=root\nCONFIG_ROOT=yes\n")
    (tmp_path / ".env.local").write_text("CONFIG_SHARED=local\nCONFIG_LOCAL=yes\n")
    (tmp_path / "scripts/.env").write_text("CONFIG_SHARED=scripts\nCONFIG_SCRIPTS=yes\n")
    with patch.dict(os.environ, {"POLYDATA_DISABLE_DOTENV": "1"}, clear=True):
        load_environment(tmp_path)
        assert "CONFIG_SHARED" not in os.environ
    with patch.dict(os.environ, {}, clear=True):
        load_environment(tmp_path)
        assert os.environ["CONFIG_SHARED"] == "root"
        assert all(os.environ[key] == "yes" for key in ("CONFIG_ROOT", "CONFIG_LOCAL", "CONFIG_SCRIPTS"))
    with patch.dict(os.environ, {"CONFIG_SHARED": "process"}, clear=True):
        load_environment(tmp_path)
        assert os.environ["CONFIG_SHARED"] == "process"


def test_imports_do_not_load_environment_files():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.path[:0] = ['scripts', '.']
import dotenv
def unexpected(*args, **kwargs):
    raise AssertionError('import loaded environment files')
dotenv.load_dotenv = unexpected
import data_sources, config, db, api.config, api.app
import telegram.bot.config, telegram.topics.config, agent.gateway.app
from agent.common.env import get_env
get_env("CONFIG_UNSET")
""",
        ],
        check=True,
    )


def test_settings_and_feed_urls_are_not_frozen_by_import(monkeypatch):
    from data_sources import rss_feeds

    monkeypatch.setenv("POLYDATA_DISABLE_DOTENV", "1")
    monkeypatch.setenv("POLYDATA_API_PORT", "18501")
    monkeypatch.setenv("POLYDATA_RSS_BBC_WORLD_URL", "https://first.invalid/feed")
    first = api_config.load_api_settings()
    assert rss_feeds()[0]["url"] == "https://first.invalid/feed"
    monkeypatch.setenv("POLYDATA_API_PORT", "18502")
    monkeypatch.setenv("POLYDATA_RSS_BBC_WORLD_URL", "https://second.invalid/feed")
    assert api_config.load_api_settings().port == 18502
    assert first.port == 18501
    assert rss_feeds()[0]["url"] == "https://second.invalid/feed"


def test_apps_keep_database_configuration_and_health_cache_isolated(monkeypatch):
    from unittest.mock import Mock
    from api.app import create_app
    from db import db

    monkeypatch.setenv("POLYDATA_API_POSTGRES_POOL_SIZE", "0")
    monkeypatch.setenv("POLYDATA_REDIS_URL", "")
    monkeypatch.setattr(db, "get_postgres_connection", lambda settings: settings["database"])
    monkeypatch.setenv("POLYDATA_POSTGRES_DATABASE", "first")
    first = create_app().extensions["polydata_runtime"]
    monkeypatch.setenv("POLYDATA_POSTGRES_DATABASE", "second")
    second = create_app().extensions["polydata_runtime"]
    try:
        for runtime in (first, second):
            runtime.resources.start_thread = Mock(return_value=True)
        assert first._api_connection_factory() == "first"
        assert second._api_connection_factory() == "second"
        from api.services.system_service import build_system_health_payload

        a = build_system_health_payload(first.system_health)
        b = build_system_health_payload(second.system_health)
        assert a["database"].endswith("/first")
        assert b["database"].endswith("/second")
        assert build_system_health_payload(first.system_health) == a
        first.resources.start_thread.assert_called_once()
        second.resources.start_thread.assert_called_once()
    finally:
        first.close()
        second.close()


def test_runtime_shutdown_stops_background_work_and_rejects_new_work():
    import threading
    import pytest
    from unittest.mock import Mock
    from api.runtime import ServiceRuntime

    factory = Mock()
    runtime = ServiceRuntime(connection_factory=factory)
    entered, finished = threading.Event(), threading.Event()

    def worker():
        entered.set()
        runtime.resources.stopped.wait()
        finished.set()

    assert runtime.resources.start_thread(worker, name="test-runtime-shutdown")
    assert entered.wait(2)
    runtime.close()
    assert finished.is_set()
    assert not runtime.resources.start_thread(lambda: None, name="closed")
    with pytest.raises(RuntimeError, match="closed"):
        runtime.start()
    runtime.close()
    factory.close.assert_called_once()


def test_connection_pool_closes_idle_and_returned_leases():
    import pytest
    from unittest.mock import Mock
    from api.db_pool import ApiPostgresConnectionPool

    connections = [Mock(), Mock()]
    pool = ApiPostgresConnectionPool(
        Mock(side_effect=connections),
        max_size=2,
        acquire_timeout_seconds=0.1,
        connect_attempts=1,
        connect_retry_delay_seconds=0,
    )
    first, second = pool.acquire(), pool.acquire()
    first.close()
    pool.close()
    connections[0].close.assert_called_once()
    connections[1].close.assert_not_called()
    second.close()
    connections[1].close.assert_called_once()
    with pytest.raises(RuntimeError, match="closed"):
        pool.acquire()


def test_connection_pool_shutdown_during_connect_closes_new_connection():
    import pytest
    from unittest.mock import Mock
    from api.db_pool import ApiPostgresConnectionPool

    connection = Mock()

    def connect():
        pool.close()
        return connection

    pool = ApiPostgresConnectionPool(
        connect, max_size=1, acquire_timeout_seconds=0.1, connect_attempts=1, connect_retry_delay_seconds=0
    )
    with pytest.raises(RuntimeError, match="closed"):
        pool.acquire()
    connection.close.assert_called_once()
