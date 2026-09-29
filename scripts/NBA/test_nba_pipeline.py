#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

_scripts_root = Path(__file__).resolve().parent.parent
if str(_scripts_root) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_scripts_root))

from db import configure_runtime_db, get_connection, init_schema
from NBA.common import ParquetLOBSink, RuntimeStateStore, write_catalog_artifacts
from NBA.nba_market_catalog import (
    _extract_matchup_pair_from_text,
    build_token_catalog_rows,
    extract_matchup_pair,
    is_head_to_head_market,
    is_explicit_playoff_event,
    merge_market_catalog_rows,
)
from NBA.query_nba_lob import query_depth, query_latest_bbo


def _has_pyarrow() -> bool:
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return False
    return True


def _has_duckdb() -> bool:
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return False
    return True


class NBAPipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmpdir.name) / "nba_lob"
        self.db_path = str(Path(self.tmpdir.name) / "main.sqlite")
        configure_runtime_db(backend="sqlite", sqlite_path=self.db_path)
        conn = get_connection(self.db_path, backend="sqlite")
        init_schema(conn=conn, db_path=self.db_path)
        conn.close()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_merge_market_catalog_rows_marks_missing_market_inactive(self) -> None:
        previous_rows = [
            {
                "market_id": 1,
                "condition_id": "0xold",
                "slug": "old-market",
                "title": "Old Market",
                "yes_token_id": "yes_old",
                "no_token_id": "no_old",
                "clob_token_ids": '["yes_old","no_old"]',
                "tags": '["nba"]',
                "enable_neg_risk": 0,
                "active": 1,
                "end_date": "2026-01-01T00:00:00Z",
                "discovered_at": "2026-01-01T00:00:00Z",
                "last_seen_at": "2026-01-05T00:00:00Z",
            }
        ]
        current_rows = {
            "0xnew": {
                "id": 2,
                "condition_id": "0xnew",
                "slug": "new-market",
                "title": "New Market",
                "yes_token_id": "yes_new",
                "no_token_id": "no_new",
                "clob_token_ids": '["yes_new","no_new"]',
                "tags": '["nba"]',
                "enable_neg_risk": 1,
                "end_date": "2026-07-01T00:00:00Z",
            }
        }
        merged = merge_market_catalog_rows(
            previous_rows,
            current_rows,
            active_condition_ids=["0xnew"],
            seen_at="2026-04-18T00:00:00+00:00",
        )
        self.assertEqual(2, len(merged))
        by_condition = {row["condition_id"]: row for row in merged}
        self.assertEqual(0, by_condition["0xold"]["active"])
        self.assertEqual("2026-01-01T00:00:00Z", by_condition["0xold"]["discovered_at"])
        self.assertEqual("2026-01-05T00:00:00Z", by_condition["0xold"]["last_seen_at"])
        self.assertEqual(1, by_condition["0xnew"]["active"])
        self.assertEqual("2026-04-18T00:00:00+00:00", by_condition["0xnew"]["discovered_at"])

    def test_build_token_catalog_rows_derives_yes_no(self) -> None:
        rows = build_token_catalog_rows(
            [
                {
                    "market_id": 7,
                    "condition_id": "0xcond",
                    "slug": "sample",
                    "title": "Sample",
                    "yes_token_id": "yes_token",
                    "no_token_id": "no_token",
                    "clob_token_ids": '["yes_token","no_token"]',
                    "active": 1,
                    "end_date": "",
                    "discovered_at": "2026-04-18T00:00:00+00:00",
                    "last_seen_at": "2026-04-18T00:00:00+00:00",
                }
            ]
        )
        self.assertEqual(2, len(rows))
        self.assertEqual("YES", rows[0]["outcome"])
        self.assertEqual("NO", rows[1]["outcome"])

    def test_playoff_detection_and_matchup_pair_extraction(self) -> None:
        playoff_event = {
            "title": "NBA Playoffs: Who Will Win Series? - Lakers vs. Rockets",
            "slug": "nba-playoffs-who-will-win-series-lakers-vs-rockets",
            "tags": [{"slug": "nba"}, {"slug": "2026-nba-playoffs"}, {"slug": "lakers"}, {"slug": "rockets"}],
        }
        game_event = {
            "title": "Rockets vs. Lakers",
            "slug": "nba-hou-lal-2026-04-18",
            "tags": [{"slug": "sports"}, {"slug": "games"}, {"slug": "nba"}],
        }
        self.assertTrue(is_explicit_playoff_event(playoff_event))
        self.assertFalse(is_explicit_playoff_event(game_event))
        self.assertEqual(("lakers", "rockets"), extract_matchup_pair(playoff_event))
        self.assertEqual(("lakers", "rockets"), extract_matchup_pair(game_event))
        self.assertIsNone(_extract_matchup_pair_from_text("Will Player AT win the 2026 NBA Finals MVP?"))

    def test_market_level_filter_keeps_only_moneyline_and_series(self) -> None:
        event = {
            "title": "Raptors vs. Cavaliers",
            "slug": "nba-tor-cle-2026-04-18",
        }
        self.assertTrue(is_head_to_head_market(event, {"question": "Raptors vs. Cavaliers: Moneyline"}))
        self.assertTrue(is_head_to_head_market(event, {"question": "Raptors vs. Cavaliers"}))
        self.assertTrue(is_head_to_head_market(event, {"question": "NBA Playoffs: Who Will Win Series? - Raptors vs. Cavaliers"}))
        self.assertFalse(is_head_to_head_market(event, {"question": "Spread: Cavaliers (-8.5)"}))
        self.assertFalse(is_head_to_head_market(event, {"question": "Raptors vs. Cavaliers: O/U 219.5"}))
        self.assertFalse(is_head_to_head_market(event, {"question": "Raptors vs. Cavaliers: 1H Moneyline"}))
        self.assertFalse(is_head_to_head_market(event, {"question": "Donovan Mitchell: Assists O/U 5.5"}))

    def test_runtime_state_store_tracks_desired_tokens_and_dedupe(self) -> None:
        store = RuntimeStateStore(self.data_root)
        try:
            store.init_schema()
            summary = store.upsert_desired_tokens(
                [
                    {
                        "market_id": 1,
                        "condition_id": "0xcond1",
                        "token_id": "token_a",
                        "outcome": "YES",
                        "outcome_index": 0,
                        "active": 1,
                    },
                    {
                        "market_id": 1,
                        "condition_id": "0xcond1",
                        "token_id": "token_b",
                        "outcome": "NO",
                        "outcome_index": 1,
                        "active": 1,
                    },
                ]
            )
            self.assertEqual(2, summary.tokens_upserted)
            self.assertEqual(["token_a", "token_b"], store.list_desired_tokens())
            self.assertTrue(
                store.claim_dedupe(
                    dedupe_key="abc",
                    stream_name="nba",
                    market_id=1,
                    token_id="token_a",
                    event_type="book",
                    event_timestamp_ms=123,
                )
            )
            self.assertFalse(
                store.claim_dedupe(
                    dedupe_key="abc",
                    stream_name="nba",
                    market_id=1,
                    token_id="token_a",
                    event_type="book",
                    event_timestamp_ms=123,
                )
            )
            second = store.upsert_desired_tokens(
                [
                    {
                        "market_id": 1,
                        "condition_id": "0xcond1",
                        "token_id": "token_a",
                        "outcome": "YES",
                        "outcome_index": 0,
                        "active": 1,
                    }
                ]
            )
            self.assertEqual(1, second.tokens_deactivated)
        finally:
            store.close()


    @unittest.skipUnless(_has_pyarrow() and _has_duckdb(), "pyarrow or duckdb not installed")
    def test_duckdb_queries_read_written_parquet(self) -> None:
        import duckdb

        market_rows = [
            {
                "market_id": 11,
                "condition_id": "0xcond_b",
                "slug": "team-b",
                "title": "Team B",
                "yes_token_id": "yes_b",
                "no_token_id": "no_b",
                "clob_token_ids": '["yes_b","no_b"]',
                "tags": '["nba"]',
                "enable_neg_risk": 0,
                "active": 1,
                "end_date": "2026-07-01T00:00:00Z",
                "discovered_at": "2026-04-18T00:00:00+00:00",
                "last_seen_at": "2026-04-18T00:00:00+00:00",
            }
        ]
        token_rows = build_token_catalog_rows(market_rows)
        write_catalog_artifacts(
            self.data_root,
            market_rows,
            token_rows,
            {"last_sync_at": "2026-04-18T00:00:00+00:00"},
        )
        sink = ParquetLOBSink(self.data_root, batch_size=1)
        sink.append_snapshot(
            {
                "dedupe_key": "snap-1",
                "market_id": 11,
                "token_id": "yes_b",
                "event_type": "book",
                "event_timestamp_ms": 1713398400000,
                "best_bid_ppm": 450000,
                "best_ask_ppm": 460000,
                "last_trade_price_ppm": None,
                "price_ppm": None,
                "size_micros": None,
                "side": None,
            }
        )
        sink.append_levels(
            [
                {
                    "dedupe_key": "snap-1",
                    "side": "bid",
                    "level_index": 0,
                    "price_ppm": 450000,
                    "size_micros": 100000000,
                }
            ]
        )
        sink.flush()
        conn = duckdb.connect()
        try:
            args = type(
                "Args",
                (),
                {
                    "data_root": str(self.data_root),
                    "market_id": 11,
                    "condition_id": None,
                    "slug": None,
                    "token_id": None,
                    "title_contains": None,
                    "event_type": None,
                    "start_time": None,
                    "end_time": None,
                    "as_of_time": None,
                    "active_only": False,
                    "limit": 10,
                },
            )()
            bbo_rows = query_latest_bbo(conn, args)
            depth_rows = query_depth(conn, args)
        finally:
            conn.close()
        self.assertEqual(1, len(bbo_rows))
        self.assertEqual(0.45, bbo_rows[0]["best_bid"])
        self.assertEqual(1, len(depth_rows))
        self.assertEqual("bid", depth_rows[0]["side"])


if __name__ == "__main__":
    unittest.main()
