from decimal import Decimal
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.orderbook.coverage import build_coverage_target, classify_priority_topic, select_orderbook_coverage_targets


def test_classifies_priority_topics_from_category_tags_and_title():
    assert classify_priority_topic({"title": "2026 FIFA World Cup winner", "tags": ["sports"]}) == "worldcup"
    assert classify_priority_topic({"category": "crypto", "title": "Bitcoin above 100k?"}) == "crypto"
    assert classify_priority_topic({"tags": '["politics", "election"]', "title": "Senate control?"}) == "politics"
    assert classify_priority_topic({"category": "weather", "title": "Rain in NYC?"}) is None
    assert classify_priority_topic({"title": "ICC T20 World Cup, Women: India vs Pakistan"}) is None


def test_build_coverage_target_assigns_hot_sampling_for_active_market():
    target = build_coverage_target({
        "market_id": 101,
        "market_slug": "2026-fifa-world-cup-winner",
        "market_title": "2026 FIFA World Cup winner",
        "category": "sports",
        "tags": ["world-cup", "soccer"],
        "yes_token_id": "yes",
        "no_token_id": "no",
        "volume_24h": "60000",
        "trade_count_24h": 220,
    })

    assert target is not None
    assert target.topic == "worldcup"
    assert target.tier == "hot"
    assert target.sample_interval_seconds == 15
    assert target.retention_days == 14
    assert target.priority_score > Decimal("0")


def test_select_coverage_targets_respects_topic_filter_and_limits():
    rows = [
        {
            "market_id": 1,
            "market_title": "Bitcoin high",
            "category": "crypto",
            "yes_token_id": "y1",
            "no_token_id": "n1",
            "trade_count_24h": 300,
        },
        {
            "market_id": 2,
            "market_title": "Election winner",
            "category": "politics",
            "yes_token_id": "y2",
            "no_token_id": "n2",
            "trade_count_24h": 100,
        },
    ]

    targets = select_orderbook_coverage_targets(rows, global_limit=10, topics=["crypto"])

    assert [target.market_id for target in targets] == [1]


def test_select_coverage_targets_fairly_mixes_requested_topics():
    rows = [
        {
            "market_id": 1,
            "market_title": "US election winner",
            "category": "politics",
            "yes_token_id": "y1",
            "no_token_id": "n1",
            "volume_24h": "200000",
        },
        {
            "market_id": 2,
            "market_title": "Another election market",
            "category": "politics",
            "yes_token_id": "y2",
            "no_token_id": "n2",
            "volume_24h": "150000",
        },
        {
            "market_id": 3,
            "market_title": "Bitcoin above 100k?",
            "category": "crypto",
            "yes_token_id": "y3",
            "no_token_id": "n3",
            "volume_24h": "1000",
        },
    ]

    targets = select_orderbook_coverage_targets(rows, global_limit=2, topics=["crypto", "politics"])

    assert [target.topic for target in targets] == ["crypto", "politics"]
