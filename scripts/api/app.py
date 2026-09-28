"""HTTP application factory. Importing this module starts no services or jobs."""

from __future__ import annotations

import atexit
import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
for path in (SCRIPTS_ROOT, SCRIPTS_ROOT.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from flask import Flask
from api.bindings import build_blueprints
from api.config import ApiSettings, load_api_settings
from api.http import register_http_hooks
from api.routes import register_blueprints
from api.runtime import ServiceRuntime
from api.services import auth_service, web_push_service
from db import add_db_cli_args, configure_db_from_args
from db.db import DatabaseSettings


def create_app(settings: ApiSettings | None = None, *, connection_factory=None, start_runtime: bool = False) -> Flask:
    settings = settings or load_api_settings()
    auth_service.validate_runtime_config()
    web_push_service.validate_runtime_config()
    app = Flask(__name__)
    runtime = ServiceRuntime(settings, application=app, connection_factory=connection_factory)
    app.extensions["polydata_runtime"] = runtime
    app.config.update(
        POLYDATA_SETTINGS=settings,
        POLYDATA_API_HOST=settings.host,
        POLYDATA_API_PORT=settings.port,
    )
    register_http_hooks(app, set(settings.allowed_origins))
    register_blueprints(app, build_blueprints(runtime))
    if start_runtime:
        atexit.register(runtime.close)
        runtime.start()
    return app


def main() -> None:
    settings = load_api_settings()
    parser = argparse.ArgumentParser(description="Polymonitor consumer API")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--skip-init-schema", action="store_true", help=argparse.SUPPRESS)
    add_db_cli_args(parser)
    args = parser.parse_args()
    configure_db_from_args(args)
    settings = replace(
        settings, host=args.host, port=args.port, db_path=args.sqlite_path, database=DatabaseSettings.from_environment()
    )
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = create_app(settings, start_runtime=True)
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
