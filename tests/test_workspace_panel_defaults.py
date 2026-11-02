import pytest

from api.services.auth_service import AuthError
from api.services.workspace_layout_service import _normalized_payload


def payload(preferences):
    return {"activePanelIds": ["crypto-watch"], "panelLayout": {}, "preferences": preferences}


def test_panel_catalog_round_trip_and_legacy_absence():
    assert "knownDefaultPanelIds" not in _normalized_payload(payload({}))[2]
    prefs = _normalized_payload(payload({"knownDefaultPanelIds": ["crypto-watch", "crypto-order-flow", "crypto-watch"]}))[2]
    assert prefs["knownDefaultPanelIds"] == ["crypto-watch", "crypto-order-flow"]
    assert _normalized_payload(payload({"knownDefaultPanelIds": []}))[2]["knownDefaultPanelIds"] == []


@pytest.mark.parametrize("invalid", [None, "crypto-watch", [42], ["bad id"], ["valid"] * 1001])
def test_panel_catalog_validation(invalid):
    with pytest.raises(AuthError):
        _normalized_payload(payload({"knownDefaultPanelIds": invalid}))
