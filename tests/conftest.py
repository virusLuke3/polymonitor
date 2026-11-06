"""Global pytest isolation from workstation and production dotenv files."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import dotenv_values
import pytest
from tempfile import TemporaryDirectory


# Unit and contract tests must opt into every credential explicitly. Without
# this guard, importing API settings can copy secrets from the developer's
# .env into os.environ and make missing-key/fallback tests order-dependent.
os.environ["POLYDATA_DISABLE_DOTENV"] = "1"

# Mocked provider tests declare their public addresses explicitly. Never load
# the workstation .env; missing-config tests may remove any individual key.
for name, value in dotenv_values(Path(__file__).parent / "fixtures/panel-sources.env").items():
    if value is not None:
        os.environ[name] = value


@pytest.fixture(autouse=True)
def isolated_read_budgets(monkeypatch):
    # Tests must not compete with production collectors on the same machine.
    with TemporaryDirectory(prefix="polymonitor-test-budgets-") as directory:
        monkeypatch.setenv("POLYDATA_READ_BUDGET_DIR", directory)
        yield

for credential_name in (
    "POLYDATA_AISSTREAM_API_KEY",
    "AISSTREAM_API_KEY",
    "POLYDATA_OPENSKY_CLIENT_ID",
    "POLYDATA_OPENSKY_CLIENT_SECRET",
    "OPENSKY_CLIENT_ID",
    "OPENSKY_CLIENT_SECRET",
    "POLYDATA_GEO_SHOCK_UCDP_ACCESS_TOKEN",
    "UCDP_API_TOKEN",
    "UCDP_API_Token",
    "UCDP_ACCESS_TOKEN",
    "UC_DP_KEY",
):
    os.environ.pop(credential_name, None)


def missing_route_dependency(*args, **kwargs):
    raise AssertionError("Test invoked an unconfigured route dependency")
