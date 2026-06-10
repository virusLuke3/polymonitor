from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.services.lob_service import _book_side_summary


def test_book_side_summary_sorts_levels_and_computes_notional_depth():
    summary = _book_side_summary({
        "bids": [
            {"price": "0.04", "size": "100"},
            {"price": "0.07", "size": "50"},
        ],
        "asks": [
            {"price": "0.98", "size": "10"},
            {"price": "0.81", "size": "20"},
        ],
    })

    assert summary["bids"][0]["price"] == "0.07"
    assert summary["asks"][0]["price"] == "0.81"
    assert summary["bestBid"] == "0.07"
    assert summary["bestAsk"] == "0.81"
    assert summary["spread"] == "0.74"
    assert summary["mid"] == "0.44"
    assert summary["bidDepth"] == "7.50"
    assert summary["askDepth"] == "26.00"
    assert summary["depthTotal"] == "33.50"
    assert summary["imbalance"].startswith("0.223880")
