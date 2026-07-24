#!/usr/bin/env python3
"""Repair open OrderFilled token-registry gaps.

This is a small operational bridge:
1. read open token gaps recorded by trades_indexer
2. rerun market discovery for those token ids
3. if a token now resolves to a real market, mark the gap resolved
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import requests

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from db import add_db_cli_args, configure_db_from_args, dict_from_row, get_connection, init_schema  # noqa: E402
from market.market_discovery import (  # noqa: E402
    _upsert_market_from_activity_trade,
    batch_upsert_markets,
    fetch_and_upsert_markets_by_token_ids_via_clob_token_lookup,
    fetch_and_upsert_markets_for_token_ids,
)
from market.market_identity import get_market_identity_by_token_id  # noqa: E402
from trade.clickhouse_orderfilled_writer import (  # noqa: E402
    ClickHouseOrderFilledSettings,
    add_clickhouse_orderfilled_cli_args,
    insert_orderfilled_fact_rows,
)
from trade.orderfilled_raw import ORDERFILLED_RAW_TABLE  # noqa: E402
from trade.orderfilled_registry_gap import (  # noqa: E402
    ORDERFILLED_REGISTRY_GAP_TABLE,
    ensure_orderfilled_registry_gap_schema,
    resolve_orderfilled_registry_gap,
)


DATA_API_BASE_URL = "https://data-api.polymarket.com"
EXCHANGE_ADDRESSES = {
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",
    "0xe111180000d2663c0091e4f400237545b87b996b",
    "0xe2222d279d744050d28e00520010520000310f59",
    "0xe3333700ca9d93003f00f0f71f8515005f6c00aa",
}


def load_gap_tokens(conn, *, limit: int, include_resolved: bool = False) -> list[str]:
    ensure_orderfilled_registry_gap_schema(conn)
    cur = conn.cursor()
    statuses = ("open", "resolved") if include_resolved else ("open",)
    placeholders = ",".join("?" for _ in statuses)
    sql = f"""
        SELECT token_id
        FROM {ORDERFILLED_REGISTRY_GAP_TABLE}
        WHERE status IN ({placeholders})
        ORDER BY last_seen_block DESC NULLS LAST, token_id
    """
    params: tuple[Any, ...] = tuple(statuses)
    if limit > 0:
        sql += " LIMIT ?"
        params = tuple(statuses) + (limit,)
    cur.execute(sql, params)
    return [str(row[0]) for row in cur.fetchall() if row and row[0]]


def load_raw_rows_for_token(conn, token_id: str, *, limit: int = 0) -> list[dict[str, Any]]:
    sql = f"""
        SELECT
            contract,
            event_version,
            event_topic,
            tx_hash,
            log_index,
            block_number,
            block_time,
            order_hash,
            maker,
            taker,
            maker_asset_id,
            taker_asset_id,
            token_id,
            side,
            price,
            size,
            maker_amount,
            taker_amount,
            fee
        FROM {ORDERFILLED_RAW_TABLE}
        WHERE token_id = ?
        ORDER BY block_number ASC, log_index ASC
    """
    params: tuple[Any, ...] = (token_id,)
    if limit > 0:
        sql += " LIMIT ?"
        params = (token_id, int(limit))
    cur = conn.execute(sql, params)
    return [dict_from_row(row) for row in cur.fetchall()]


def build_fact_rows_from_raw(raw_rows: list[dict[str, Any]], identity, token_id: str) -> list[dict[str, Any]]:
    token_text = str(token_id)
    if str(identity.yes_token_id or "") == token_text:
        outcome = "YES"
    elif str(identity.no_token_id or "") == token_text:
        outcome = "NO"
    else:
        return []
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        rows.append(
            {
                "tx_hash": raw.get("tx_hash"),
                "log_index": raw.get("log_index"),
                "market_id": identity.local_market_id,
                "condition_id": identity.condition_id or "",
                "maker": raw.get("maker"),
                "taker": raw.get("taker"),
                "price": raw.get("price"),
                "size": raw.get("size"),
                "side": raw.get("side"),
                "outcome": outcome,
                "token_id": raw.get("token_id"),
                "block_number": raw.get("block_number"),
                "timestamp": raw.get("block_time"),
                "order_hash": raw.get("order_hash"),
                "maker_asset_id": raw.get("maker_asset_id"),
                "taker_asset_id": raw.get("taker_asset_id"),
                "maker_amount": raw.get("maker_amount"),
                "taker_amount": raw.get("taker_amount"),
                "fee": raw.get("fee"),
                "contract": raw.get("contract"),
                "created_at": None,
            }
        )
    return rows


def _non_exchange_user(raw: dict[str, Any]) -> str:
    for key in ("maker", "taker"):
        address = str(raw.get(key) or "").strip().lower()
        if address and address not in EXCHANGE_ADDRESSES:
            return address
    return ""


def _combo_category_from_title(title: str) -> str:
    text = title.lower()
    sports_terms = (
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "soccer",
        "tennis",
        "ufc",
        "wnba",
        "spread:",
        " o/u ",
        " vs. ",
    )
    if any(term in text for term in sports_terms):
        return "sports"
    if any(term in text for term in ("bitcoin", "btc", "ethereum", "eth", "solana", "crypto")):
        return "crypto"
    if any(term in text for term in ("trump", "election", "senate", "president")):
        return "politics"
    return "combo"


def _combo_tokens_from_activity(activity: dict[str, Any], token_id: str) -> tuple[str, str]:
    # Data API conditionId is not the ERC1155 position id. Combo assets still
    # arrive as adjacent CTF token ids, so derive the YES/NO pair from token_id.
    token_int = int(str(token_id))
    base_int = token_int if token_int % 2 == 0 else token_int - 1
    return str(base_int), str(base_int + 1)


def find_data_api_activity_trade_for_raw(raw: dict[str, Any], *, timeout: float = 10.0) -> dict[str, Any] | None:
    user = _non_exchange_user(raw)
    token_id = str(raw.get("token_id") or "").strip()
    tx_hash = str(raw.get("tx_hash") or "").strip().lower()
    if not user or not token_id or not tx_hash:
        return None
    try:
        resp = requests.get(
            f"{DATA_API_BASE_URL}/activity",
            params={"user": user, "type": "TRADE", "limit": "100"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        resp.close()
    except Exception:
        return None
    if not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, dict):
            continue
        if str(item.get("transactionHash") or "").strip().lower() != tx_hash:
            continue
        if str(item.get("asset") or "").strip() != token_id:
            continue
        return item
    return None


def upsert_combo_market_from_activity(raw: dict[str, Any], token_id: str, *, db_path: str) -> int:
    return _upsert_market_from_activity_trade(
        token_id=token_id,
        tx_hash=str(raw.get("tx_hash") or ""),
        maker=str(raw.get("maker") or ""),
        taker=str(raw.get("taker") or ""),
        db_path=db_path,
    )


def is_real_identity(conn, token_id: str, identity) -> bool:
    if not identity or not identity.local_market_id:
        return False
    row = conn.execute(
        """
        SELECT category, slug, yes_token_id, no_token_id
        FROM markets
        WHERE id = ?
        LIMIT 1
        """,
        (int(identity.local_market_id),),
    ).fetchone()
    if not row:
        return False
    market = dict_from_row(row)
    category = str(market.get("category") or "")
    slug = str(market.get("slug") or "")
    if category == "orderfilled-placeholder" or slug.startswith("trade-indexer-placeholder-"):
        return False
    token_text = str(token_id)
    return token_text in {str(market.get("yes_token_id") or ""), str(market.get("no_token_id") or "")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile open OrderFilled token registry gaps.")
    add_db_cli_args(parser)
    add_clickhouse_orderfilled_cli_args(parser)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--requests-delay", type=float, default=0.0)
    parser.add_argument(
        "--discovery-mode",
        choices=("full", "clob-token", "none"),
        default="full",
        help="full uses multi-stage discovery; clob-token only calls official /markets-by-token; none only uses local markets.",
    )
    parser.add_argument("--include-resolved", action="store_true", help="Also scan previously resolved gaps for missing raw->fact repair.")
    parser.add_argument("--write-clickhouse-fact", action="store_true", help="Backfill resolved raw OrderFilled rows into ClickHouse orderfilled_fact.")
    parser.add_argument("--activity-fallback", action="store_true", help="Use Data API /activity to recover combo markets that CLOB /markets-by-token cannot resolve.")
    parser.add_argument("--raw-row-limit-per-token", type=int, default=0, help="Limit raw rows loaded per token; 0 means no limit.")
    parser.add_argument("--token-id", action="append", default=[], help="Repair a specific token id. Can be repeated; bypasses --limit selection.")
    parser.add_argument("--dry-run", action="store_true", help="Discover and report without marking gaps resolved or writing ClickHouse.")
    args = parser.parse_args()

    configure_db_from_args(args)
    init_schema(db_path=args.sqlite_path)
    tokens = [str(item).strip() for item in args.token_id if str(item or "").strip()]
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        conn = get_connection(args.sqlite_path)
        try:
            tokens = load_gap_tokens(
                conn,
                limit=max(0, int(args.limit)),
                include_resolved=bool(args.include_resolved),
            )
        finally:
            conn.close()

    if not tokens:
        print({"gap_tokens": 0, "upserted_markets": 0, "resolved_tokens": 0, "fact_rows": 0})
        return

    if args.discovery_mode == "none":
        upserted = 0
    elif args.discovery_mode == "clob-token":
        upserted = fetch_and_upsert_markets_by_token_ids_via_clob_token_lookup(
            tokens,
            db_path=args.sqlite_path,
        )
    else:
        upserted = fetch_and_upsert_markets_for_token_ids(
            tokens,
            db_path=args.sqlite_path,
            max_pages=max(0, int(args.max_pages)),
            requests_delay=float(args.requests_delay),
        )

    conn = get_connection(args.sqlite_path)
    try:
        resolved = 0
        unresolved = 0
        raw_rows_seen = 0
        fact_rows_ready = 0
        fact_rows_written = 0
        activity_upserted = 0
        clickhouse_settings = ClickHouseOrderFilledSettings(
            container=args.clickhouse_container,
            database=args.clickhouse_database,
            user=args.clickhouse_user,
            password=args.clickhouse_password,
            orderfilled_insert_table=args.clickhouse_orderfilled_insert_table,
        )
        if args.write_clickhouse_fact and not args.clickhouse_password:
            raise SystemExit("--clickhouse-password or CLICKHOUSE_PASSWORD is required with --write-clickhouse-fact")
        for token_id in tokens:
            identity = get_market_identity_by_token_id(conn, token_id)
            if not is_real_identity(conn, token_id, identity) and args.activity_fallback:
                sample_rows = load_raw_rows_for_token(conn, token_id, limit=1)
                if sample_rows and not args.dry_run:
                    activity_upserted += upsert_combo_market_from_activity(
                        sample_rows[0],
                        token_id,
                        db_path=args.sqlite_path,
                    )
                    identity = get_market_identity_by_token_id(conn, token_id)
            if not is_real_identity(conn, token_id, identity):
                unresolved += 1
                continue

            fact_rows: list[dict[str, Any]] = []
            if args.write_clickhouse_fact:
                raw_rows = load_raw_rows_for_token(
                    conn,
                    token_id,
                    limit=max(0, int(args.raw_row_limit_per_token)),
                )
                raw_rows_seen += len(raw_rows)
                fact_rows = build_fact_rows_from_raw(raw_rows, identity, token_id)
                fact_rows_ready += len(fact_rows)
                if fact_rows and not args.dry_run:
                    fact_rows_written += insert_orderfilled_fact_rows(
                        clickhouse_settings,
                        fact_rows,
                        skip_existing=True,
                    )

            if not args.dry_run:
                resolve_orderfilled_registry_gap(
                    conn,
                    token_id=token_id,
                    market_id=identity.local_market_id,
                    condition_id=identity.condition_id,
                    resolution_source="reconcile_orderfilled_registry_gaps",
                )
            resolved += 1
    finally:
        conn.close()

    print(
        {
            "gap_tokens": len(tokens),
            "upserted_markets": int(upserted),
            "resolved_tokens": int(resolved),
            "unresolved_tokens": int(unresolved),
            "raw_rows_seen": int(raw_rows_seen),
            "fact_rows_ready": int(fact_rows_ready),
            "fact_rows_written": int(fact_rows_written),
            "activity_upserted": int(activity_upserted),
            "dry_run": bool(args.dry_run),
        }
    )


if __name__ == "__main__":
    main()
