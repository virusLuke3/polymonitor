"""Global pytest isolation from workstation and production dotenv files."""

from __future__ import annotations

import os


# Unit and contract tests must opt into every credential explicitly. Without
# this guard, importing API settings can copy secrets from the developer's
# .env into os.environ and make missing-key/fallback tests order-dependent.
os.environ["POLYDATA_DISABLE_DOTENV"] = "1"

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
