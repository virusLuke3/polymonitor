"""Read the existing Market registry, observations, and Oracle events.

No collector, exchange HTTP fallback, retired serving table, or history rebuild
is on this path. Every SQL statement has read-only and resource limits.
"""
from __future__ import annotations

import json
import math
import hashlib

from api.read_budget import take_read_token, try_permit
from api.serialization import normalize_market, normalize_oracle_event
from api.services.panel_read_cache import PanelReadCache, utc_now
from market.market_identity import MarketIdentity, oracle_event_lookup_terms
from market.market_serving_identity import binary_serving_identity_sql


RANGES = {"1h": 3600, "6h": 21600, "1d": 86400, "1w": 604800, "1m": 2592000, "all": 2592000}


def number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def read_query(connection_factory, database_path, sql, params=()):
    permit = try_permit("panel-postgres", 2)
    if permit is None:
        raise TimeoutError("Panel PostgreSQL budget full")
    with permit:
        if not take_read_token("panel-postgres", per_second=8, burst=8):
            raise TimeoutError("Panel PostgreSQL rate budget full")
        connection = connection_factory(database_path)
        try:
            cursor = connection.cursor()
            # One round trip across the existing database tunnel, rather
            # than seven sequential setup round trips per bounded query.
            cursor.execute("SET TRANSACTION READ ONLY; "
                           "SET LOCAL statement_timeout = '1000ms'; "
                           "SET LOCAL lock_timeout = '100ms'; "
                           "SET LOCAL work_mem = '4MB'; "
                           "SET LOCAL max_parallel_workers_per_gather = 0; "
                           "SET LOCAL jit = off; SET LOCAL enable_hashjoin = off")
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            connection.close()


def market_rows(query, where, params, *, limit=100, candidates=None):
    # Materialize the indexed candidate window before identity/lifecycle
    # checks. LIMIT after a broad anti-join can otherwise scan the registry.
    candidate_where = "m.created_at IS NOT NULL" if candidates else where
    selected_where = where if candidates else "TRUE"
    bound = (candidates, *params, limit) if candidates else (*params, limit, limit)
    return query(f"""
        WITH candidates AS MATERIALIZED (
            SELECT m.* FROM core.markets m WHERE {candidate_where}
            ORDER BY m.created_at DESC NULLS LAST, m.id DESC LIMIT ?
        ), selected AS MATERIALIZED (
            SELECT m.* FROM candidates m WHERE {selected_where}
            AND {binary_serving_identity_sql('m', qualified_ops=True)}
        )
        SELECT m.*, c.source_payload AS catalog_payload, c.source_updated_at AS quote_updated_at,
            c.last_seen_at AS catalog_observed_at, s.completion_status, s.is_resolved, s.is_final,
            s.settlement_outcome, s.settlement_source, s.updated_at AS oracle_updated_at,
            mlp.latest_yes_price, mlp.latest_no_price, mlp.latest_trade_at AS price_updated_at
        FROM selected m
        LEFT JOIN core.market_catalog c ON c.gamma_market_id = m.gamma_market_id
            AND c.source_payload->>'conditionId' = m.condition_id
        LEFT JOIN core.market_status_snapshot s ON s.market_id = m.id
        LEFT JOIN core.market_latest_prices mlp ON mlp.market_id = m.id
        ORDER BY mlp.latest_trade_at DESC NULLS LAST, m.created_at DESC NULLS LAST, m.id DESC LIMIT ?
    """, bound)


class MarketPanelReader:
    def __init__(self, runtime):
        self.runtime = runtime
        self.cache = PanelReadCache(runtime)

    def query(self, sql, params=()):
        return read_query(self.runtime._api_connection_factory, self.runtime.SETTINGS.database.sqlite_path, sql, params)

    def _rows(self, where, params, *, limit=100, candidates=None):
        return market_rows(self.query, where, params, limit=limit, candidates=candidates)

    def record(self, market_id):
        def build():
            rows = self._rows("m.id = ?", (int(market_id),), limit=1)
            if not rows:
                return {"_status": 404, "error": "Market identity not available", "marketId": int(market_id)}
            return {"row": rows[0]}
        value = self.cache.get("record", int(market_id), build, ttl=60, max_age=300, admit=False)
        if value.get("_status") == 404:
            raise LookupError("Market identity not available")
        if not value.get("row"):
            raise TimeoutError("Market registry unavailable")
        return value["row"]

    def semantic_query(self, sql, params=()):
        # Cache source evidence, never a caller-supplied capability assertion.
        # The public projector still validates identity and every value on each
        # response. Expired evidence fails closed without stale reuse.
        key = [hashlib.sha256(sql.encode()).hexdigest(), list(params or ())]
        # Receipts repeat the same plan JSON for every token. Intern only those
        # JSON documents; preserve every source field and revalidate on read.
        fields = ("receipt_plan_json", "receipt_record_json", "receipt_before_images_json")
        def build():
            rows = self.query(sql, params)
            documents, indexes = [], {}
            for row in rows:
                for field in fields:
                    if field not in row:
                        continue
                    value = row[field]
                    encoded = json.dumps(value, sort_keys=True, default=str)
                    if encoded not in indexes:
                        indexes[encoded] = len(documents)
                        documents.append(value)
                    row[field] = indexes[encoded]
            return {"rows": rows, "documents": documents}
        payload = self.cache.get("semantics-v2", key, build, ttl=30, max_age=0, admit=False)
        if payload.get("status") != "ok":
            raise TimeoutError("Source outcome evidence unavailable")
        for row in payload["rows"]:
            for field in fields:
                if field in row:
                    row[field] = payload["documents"][row[field]]
        return payload["rows"]

    @staticmethod
    def _item(row):
        payload = row.get("catalog_payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        yes, no = number(row.get("latest_yes_price")), number(row.get("latest_no_price"))
        state = "Closed" if row.get("closed") is True else "Active" if row.get("active") is True and row.get("closed") is False else "Unknown"
        item = normalize_market({**row, "status": state, "latest_price": yes, "latest_yes_price": yes, "latest_no_price": no,
                                 "completion_status": row.get("completion_status") or "UNKNOWN"})
        item.update(volume24h=number(payload.get("volume24hr")), tradeCount24h=None, price24hAgo=None,
                    lastTradeAt=None, quoteUpdatedAt=row.get("price_updated_at"),
                    observedAt=row.get("catalog_observed_at"), priceSource="stored-trade", change24h=number(payload.get("oneDayPriceChange")))
        return item

    def catalog(self, *, query="", page=1, page_size=50, status="active"):
        query = str(query or "").strip()[:160]
        page_size = min(100, max(1, int(page_size)))
        if int(page) != 1:
            raise ValueError("Use search to select markets outside the current catalog page")
        def build():
            filters, params = ["m.active IS TRUE", "m.closed IS FALSE", "(m.end_date IS NULL OR m.end_date >= now())"], []
            if query:
                if query.startswith("0x") and len(query) == 66:
                    filters, params = ["m.condition_id = ?"], [query.lower()]
                else:
                    filters.append("to_tsvector('simple', coalesce(m.title,'') || ' ' || coalesce(m.slug,'') || ' ' || coalesce(m.category,'')) @@ plainto_tsquery('simple', ?)")
                    params.append(query)
            else:
                filters.extend(["m.slug NOT LIKE '%%updown-5m%%'", "m.slug NOT LIKE '%%updown-15m%%'", "m.title NOT LIKE '%% Up or Down - %%'"])
            rows = self._rows(" AND ".join(filters), params, limit=page_size + 1, candidates=5000 if not query else None)
            items = [self._item(row) for row in rows[:page_size]]
            return {"items": items, "pagination": {"page": 1, "pageSize": page_size, "hasMore": len(rows) > page_size},
                    "coverage": "page-from-latest-5000-registry-candidates", "source": "market-data/postgresql", "generatedAt": utc_now()}
        return self.cache.get("catalog", [query, page_size], build, ttl=45, max_age=300)

    def groups(self, *, query="", page=1, page_size=50, sort="active"):
        catalog = self.catalog(query=query, page=page, page_size=page_size)
        # Each visible card is a canonical binary market. Event expansion is
        # fetched only on selection, never for all catalog rows.
        return {**catalog, "items": [self._group([item]) for item in catalog.get("items", [])]}

    @staticmethod
    def _group(items, event_id=None, title=None):
        first = items[0]
        outcomes = [{"outcomeKey": str(i["id"]), "marketId": i["id"], "localMarketId": i["id"],
                     "gammaMarketId": i.get("gammaMarketId"), "label": i["title"], "title": i["title"],
                     "yesPrice": i.get("latestYesPrice"), "noPrice": i.get("latestNoPrice"),
                     "conditionId": i.get("conditionId"), "yesTokenId": i.get("yesTokenId"), "noTokenId": i.get("noTokenId"),
                     "volume24h": i.get("volume24h"), "tradeCount24h": None, "lastTradeAt": None,
                     "volumeSource": "stored-catalog", "volumeScope": "market", "slug": i.get("slug")} for i in items]
        return {"groupId": f"event:{event_id}" if event_id else f"market:{first['id']}", "eventId": event_id,
                "title": title or first["title"], "category": first.get("category"), "tags": first.get("tags", []),
                "createdAt": first.get("createdAt"), "endDate": first.get("endDate"),
                "volume24h": first.get("volume24h") if len(items) == 1 else None, "tradeCount24h": None,
                "volumeScope": "market", "volumeSource": "stored-catalog", "outcomeCount": len(items),
                "defaultMarketId": first["id"], "defaultOutcomeKey": str(first["id"]), "outcomes": outcomes,
                "topOutcomes": outcomes[:5], "lastActivityAt": None, "generatedAt": utc_now()}

    def group_detail(self, event_id):
        def build():
            rows = self._rows("m.event_id = ?", (str(event_id),), limit=101)
            if not rows:
                return {"_status": 404, "error": "Event not found"}
            return {**self._group([self._item(r) for r in rows[:100]], event_id, rows[0].get("event_title")),
                    "hasMore": len(rows) > 100, "coverage": "first-100-outcomes"}
        return self.cache.get("group", str(event_id), build, ttl=60, max_age=300)

    def group_chart(self, event_id, *, range_name="1d"):
        group = self.group_detail(event_id)
        market_id = group.get("defaultMarketId")
        chart = self.chart(market_id, range_name=range_name) if market_id else {}
        return {"eventId": event_id, "range": range_name, "coverage": "default-outcome-only",
                "historyStatus": chart.get("historyStatus", "unavailable"), "status": chart.get("status", "unavailable"),
                "series": [{"marketId": market_id, "label": group.get("title"),
                            "points": [{"timestamp": p["timestamp"], "price": p["yesPrice"]}
                                       for p in chart.get("points", []) if p.get("yesPrice") is not None]}] if market_id else []}

    def detail(self, market_id):
        row = self.record(market_id)
        item = self._item(row)
        identity = {**MarketIdentity.from_row(row).as_api_dict(), "marketId": int(market_id)}
        price = {"marketId": int(market_id), "latestPrice": item["latestPrice"], "latestYesPrice": item["latestYesPrice"],
                 "latestNoPrice": item["latestNoPrice"], "volume24h": item["volume24h"], "tradeCount24h": None,
                 "updatedAt": row.get("price_updated_at"), "priceSource": "stored-trade"}
        return {"market": item, "identity": identity, "price": price, "localMarketId": int(market_id),
                "servingSource": "market-data/postgresql", "servingUpdatedAt": row.get("catalog_observed_at"),
                "focusStatus": "ready", "generatedAt": utc_now()}


    def health(self):
        from api.services.panel_read_cache import NAMESPACE
        components = {layer: self.runtime.SNAPSHOT_STORE.get(NAMESPACE + ":health", layer) or {"status": "unknown"}
                      for layer in ("catalog", "record", "oracle", "flow", "chart")}
        return {"status": "degraded" if any(c["status"] == "unavailable" for c in components.values()) else "observed",
                "scope": "recent-reads-only", "components": components,
                "lob": {"status": "unknown", "source": "per-book-response"},
                "budgets": {"postgresConnectionsPerHost": 4, "panelPostgresQueries": 2,
                            "panelClickHouseRequests": 2, "panelClickHouseRequestsPerSecond": 1,
                            "panelPostgresQueriesPerSecond": 8, "postgresStatementMs": 1000,
                            "clickHouseReadMiBPerRequest": 64}}

    def flow(self, market_id, *, limit=50, before=None, offset=0):
        from api.services.panel_trade_reader import read_flow
        if offset:
            raise ValueError("Use a trade cursor")
        return read_flow(self, market_id, limit=limit, before=before)


    def by_id(self, market_id):
        try:
            return self.record(market_id)
        except LookupError:
            return None

    def by_slug(self, slug):
        def build():
            rows = self._rows("m.slug = ?", (str(slug)[:256],), limit=1)
            return {"row": rows[0] if rows else None}
        payload = self.cache.get("slug", str(slug)[:256], build, ttl=60, max_age=300)
        if payload.get("status") in {"warming", "unavailable"}:
            raise TimeoutError("Market registry unavailable")
        return payload.get("row")

    def search(self, query, limit=10):
        if not str(query or "").strip():
            return {"items": []}
        return self.catalog(query=query, page_size=min(50, max(1, int(limit))))

    def book(self, market_id):
        from api.services.lob_service import get_runtime_lob_by_token_payload
        row = self.record(market_id)
        return get_runtime_lob_by_token_payload(row.get("yes_token_id"), no_token_id=row.get("no_token_id"),
                                                market_title=row.get("title"), market_id=market_id)

    def trades(self, market_id, **kwargs):
        payload = self.flow(market_id, **kwargs)
        if payload.get("status") in {"warming", "unavailable"}:
            raise TimeoutError("Trade source unavailable")
        return payload.get("items", [])

    def workspace(self, market_id):
        # Compatibility endpoint. The current UI fetches these independently.
        detail = self.detail(market_id)
        oracle = self.oracle(market_id)
        chart = self.chart(market_id)
        flow = self.flow(market_id)
        return {**detail, "oracle": oracle, "oracleEvents": oracle.get("timeline", []), "chart": chart,
                "trades": flow.get("items", []), "flowStatus": flow.get("status"), "flowCoverage": flow.get("coverage")}

    def oracle(self, market_id):
        def build():
            row = self.record(market_id)
            terms = oracle_event_lookup_terms(MarketIdentity.from_row(row))
            branches = [f"(SELECT * FROM oracle.oracle_events WHERE {column} = ? ORDER BY block_number DESC, id DESC LIMIT 51)" for column, _ in terms]
            events = self.query(f"""WITH matched AS ({' UNION ALL '.join(branches)}),
                unique_events AS (SELECT DISTINCT ON (id) * FROM matched ORDER BY id)
                SELECT * FROM unique_events ORDER BY block_number DESC, id DESC LIMIT 51""", [v for _, v in terms])
            timeline = [normalize_oracle_event({**e, "market_id": int(market_id), "market_title": row["title"]}) for e in reversed(events[:50])]
            state = row.get("completion_status") or ("CLOSED" if row.get("closed") is True else "OPEN" if row.get("active") is True and row.get("closed") is False else "UNKNOWN")
            return {**MarketIdentity.from_row(row).as_api_dict(), "marketId": int(market_id), "oracle": row.get("oracle"),
                    "currentStatus": state, "completionStatus": state, "isTradingClosed": row.get("closed"),
                    "isResolved": row.get("is_resolved"), "isFinal": row.get("is_final"),
                    "settlementOutcome": row.get("settlement_outcome") or "UNKNOWN", "settlementSource": row.get("settlement_source"),
                    "updatedAt": row.get("oracle_updated_at") or row.get("market_state_observed_at"),
                    "timeline": timeline, "hasMore": len(events) > 50, "coverage": "latest-50-events"}
        return {"marketId": int(market_id), "localMarketId": int(market_id), **self.cache.get("oracle", int(market_id), build, ttl=20, max_age=120)}

    def chart(self, market_id, *, range_name="1d", interval="5m"):
        if range_name not in RANGES:
            raise ValueError("Unsupported chart range")
        from api.services.panel_trade_reader import read_chart
        return read_chart(self, market_id, range_name=range_name)
