from __future__ import annotations

import os
import unittest
from unittest.mock import patch


from api.services import query_service


class QueryServiceClickHouseTestCase(unittest.TestCase):
    def test_recent_trades_raises_when_clickhouse_enabled_but_unavailable(self):
        ctx = {"get_existing_trade_read_source": lambda: None}
        with patch.object(query_service.clickhouse_orderfilled_service, "get_recent_trades", return_value=None), patch.object(
            query_service.clickhouse_orderfilled_service,
            "clickhouse_orderfilled_enabled",
            return_value=True,
        ), patch.dict(os.environ, {"POLYDATA_ORDERFILLED_CLICKHOUSE_FALLBACK_ON_UNAVAILABLE": "0"}, clear=False):
            with self.assertRaisesRegex(TimeoutError, "ClickHouse OrderFilled read is enabled but unavailable"):
                query_service.get_recent_trades(ctx, limit=3)

    def test_recent_trade_route_reports_failure_then_recovers(self):
        from dataclasses import fields
        from flask import Flask
        from api.routes.markets import MarketRouteDependencies, create_markets_blueprint
        ctx = {"get_existing_trade_read_source": lambda: None}
        dependencies = {field.name: lambda *args, **kwargs: None for field in fields(MarketRouteDependencies)}
        dependencies['sanitize_payload'] = lambda payload, **kwargs: payload
        dependencies['get_recent_trades_snapshot'] = lambda limit: query_service.get_recent_trades(ctx, limit=limit)
        app = Flask(__name__)
        app.register_blueprint(create_markets_blueprint(MarketRouteDependencies(**dependencies)))
        observed = [{'marketId': 11, 'txHash': 'observed-transaction', 'blockNumber': 123}]
        with patch.object(query_service.clickhouse_orderfilled_service, 'get_recent_trades', side_effect=[None, observed]), patch.object(
            query_service.clickhouse_orderfilled_service, 'clickhouse_orderfilled_enabled', return_value=True
        ), patch.dict(os.environ, {'POLYDATA_ORDERFILLED_CLICKHOUSE_FALLBACK_ON_UNAVAILABLE': '0'}, clear=False):
            failed = app.test_client().get('/trades/recent?limit=3')
            self.assertEqual(failed.status_code, 503)
            self.assertEqual(failed.get_json()['status'], 'unavailable')
            recovered = app.test_client().get('/trades/recent?limit=3')
            self.assertEqual(recovered.status_code, 200)
            self.assertEqual(recovered.get_json(), observed)

    def test_empty_recent_window_requires_current_fact_projection(self):
        service = query_service.clickhouse_orderfilled_service
        for latest, expected in [(99, None), (100, []), (110, [])]:
            with self.subTest(latest=latest), patch.object(service, '_recent_block_range', return_value=(100, 110)), patch.object(
                service, '_query_json_rows', side_effect=[[], [{'latest_block': latest}]]
            ) as read:
                self.assertEqual(service.get_recent_trades({}), expected)
                self.assertIn('system.parts', read.call_args_list[-1].args[1])
        with patch.object(service, '_recent_block_range', return_value=(100,110)), patch.object(
            service, '_query_json_rows', side_effect=[[], None]
        ):
            self.assertIsNone(service.get_recent_trades({}))
