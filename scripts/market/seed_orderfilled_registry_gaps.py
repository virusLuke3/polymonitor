#!/usr/bin/env python3
"""Seed historical OrderFilled token-registry gaps from ClickHouse fact history.

This script is the historical companion to the live `trades_indexer` gap
tracking. It scans aggregated `orderfilled_fact` tokens, checks whether the
current PostgreSQL token registry can resolve them to a real market, and writes
durable OPEN gaps for tokens that are still unresolved or placeholder-only.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_ROOT.parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from db import configure_runtime_db, get_connection  # noqa: E402
from trade.orderfilled_registry_gap import (  # noqa: E402
    ensure_orderfilled_registry_gap_schema,
    seed_orderfilled_registry_gap_snapshot,
)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class TokenSummary:
    token_hex: str
    token_decimal: str
    first_seen_block: int | None
    last_seen_block: int | None
    first_tx_hash: str
    last_tx_hash: str
    first_log_index: int | None
    last_log_index: int | None
    sample_market_id: int | None
    seen_count: int


@dataclass(frozen=True)
class RegistryMatch:
    token_id: str
    market_id: int
    condition_id: str
    category: str
    slug: str


def clickhouse_cmd(args: argparse.Namespace, query: str) -> list[str]:
    return [
        "docker",
        "exec",
        "-i",
        args.clickhouse_container,
        "clickhouse-client",
        "--database",
        args.clickhouse_database,
        "--user",
        args.clickhouse_user,
        "--password",
        args.clickhouse_password,
        "--query",
        query,
    ]


def clickhouse_token_hex_to_decimal(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text.startswith("0x"):
        text = text[2:]
    if text.isdigit():
        return text
    if re.fullmatch(r"[0-9a-f]{1,64}", text):
        try:
            return str(int(text, 16))
        except ValueError:
            return ""
    return ""


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def is_placeholder_market(row: RegistryMatch | dict[str, Any] | None) -> bool:
    if not row:
        return False
    category = str(row["category"] if isinstance(row, dict) else row.category or "").strip().lower()
    slug = str(row["slug"] if isinstance(row, dict) else row.slug or "").strip().lower()
    return category == "orderfilled-placeholder" or slug.startswith("trade-indexer-placeholder-")


def pg_connect(args: argparse.Namespace):
    configure_runtime_db(
        backend="postgres",
        postgres_host=args.postgres_host,
        postgres_port=args.postgres_port,
        postgres_user=args.postgres_user,
        postgres_password=args.postgres_password,
        postgres_database=args.postgres_database,
        postgres_search_path="core,oracle,ops,public",
    )
    return get_connection(backend="postgres")


def load_registry_matches(conn, token_ids: list[str]) -> dict[str, RegistryMatch]:
    matches: dict[str, RegistryMatch] = {}
    if not token_ids:
        return matches
    cur = conn.cursor()
    try:
        for chunk in chunked(token_ids, 5000):
            cur.execute(
                """
                SELECT
                    mt.token_id,
                    mt.market_id,
                    mt.condition_id,
                    COALESCE(m.category, '') AS category,
                    COALESCE(m.slug, '') AS slug
                FROM core.market_tokens mt
                JOIN core.markets m ON m.id = mt.market_id
                WHERE mt.token_id = ANY(%s)
                """,
                (chunk,),
            )
            for row in cur.fetchall():
                token_id = str(row["token_id"] or "")
                if not token_id:
                    continue
                matches[token_id] = RegistryMatch(
                    token_id=token_id,
                    market_id=int(row["market_id"]),
                    condition_id=str(row["condition_id"] or ""),
                    category=str(row["category"] or ""),
                    slug=str(row["slug"] or ""),
                )
    finally:
        cur.close()
    return matches


def build_clickhouse_summary_query(args: argparse.Namespace) -> str:
    filters = ["token_id != ''"]
    if args.min_block is not None:
        filters.append(f"block_number >= {int(args.min_block)}")
    if args.max_block is not None:
        filters.append(f"block_number <= {int(args.max_block)}")
    where_sql = " AND ".join(filters)
    limit_sql = f"LIMIT {int(args.limit_tokens)}" if int(args.limit_tokens or 0) > 0 else ""
    return f"""
        SELECT
            token_id,
            min(block_number) AS first_seen_block,
            max(block_number) AS last_seen_block,
            argMin(tx_hash, tuple(block_number, log_index)) AS first_tx_hash,
            argMax(tx_hash, tuple(block_number, log_index)) AS last_tx_hash,
            argMin(log_index, tuple(block_number, log_index)) AS first_log_index,
            argMax(log_index, tuple(block_number, log_index)) AS last_log_index,
            any(market_id) AS sample_market_id,
            count() AS seen_count
        FROM orderfilled_fact
        WHERE {where_sql}
        GROUP BY token_id
        {limit_sql}
        FORMAT TabSeparated
    """


def iter_clickhouse_token_summaries(args: argparse.Namespace) -> Iterator[TokenSummary]:
    proc = subprocess.Popen(
        clickhouse_cmd(args, build_clickhouse_summary_query(args)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    try:
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 9:
                continue
            token_hex = str(parts[0] or "").strip().lower()
            yield TokenSummary(
                token_hex=token_hex,
                token_decimal=clickhouse_token_hex_to_decimal(token_hex),
                first_seen_block=int(parts[1]) if parts[1] else None,
                last_seen_block=int(parts[2]) if parts[2] else None,
                first_tx_hash=str(parts[3] or "").strip(),
                last_tx_hash=str(parts[4] or "").strip(),
                first_log_index=int(parts[5]) if parts[5] else None,
                last_log_index=int(parts[6]) if parts[6] else None,
                sample_market_id=int(parts[7]) if parts[7] else None,
                seen_count=int(parts[8]) if parts[8] else 0,
            )
    finally:
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        return_code = proc.wait()
        if return_code != 0:
            raise RuntimeError(f"clickhouse-client failed with exit code {return_code}: {stderr[:800].strip()}")


def note_for_summary(summary: TokenSummary, match: RegistryMatch | None) -> tuple[bool, str, int | None]:
    if not summary.token_decimal:
        return True, "historical seed: token_id in orderfilled_fact is not convertible to a canonical decimal token id", summary.sample_market_id
    if match is None:
        return True, "historical seed: token has historical orderfilled_fact rows but no current market_tokens registry mapping", summary.sample_market_id
    if is_placeholder_market(match):
        return True, "historical seed: token currently maps only to an orderfilled-placeholder market", match.market_id
    return False, "", match.market_id


def seed_historical_gaps(args: argparse.Namespace) -> dict[str, int]:
    counts = {
        "scanned_tokens": 0,
        "convertible_tokens": 0,
        "real_registry_tokens": 0,
        "placeholder_only_tokens": 0,
        "missing_registry_tokens": 0,
        "seeded_open_gaps": 0,
    }

    conn = pg_connect(args)
    try:
        ensure_orderfilled_registry_gap_schema(conn)
        batch: list[TokenSummary] = []
        for summary in iter_clickhouse_token_summaries(args):
            counts["scanned_tokens"] += 1
            if summary.token_decimal:
                counts["convertible_tokens"] += 1
            batch.append(summary)
            if len(batch) >= args.batch_size:
                _flush_batch(conn, batch, args, counts)
                batch.clear()
        if batch:
            _flush_batch(conn, batch, args, counts)
    finally:
        conn.close()
    return counts


def _flush_batch(
    conn,
    batch: list[TokenSummary],
    args: argparse.Namespace,
    counts: dict[str, int],
) -> None:
    registry = load_registry_matches(
        conn,
        [item.token_decimal for item in batch if item.token_decimal],
    )
    for summary in batch:
        match = registry.get(summary.token_decimal)
        should_seed, note, effective_market_id = note_for_summary(summary, match)
        if match is not None and not is_placeholder_market(match):
            counts["real_registry_tokens"] += 1
        elif match is not None:
            counts["placeholder_only_tokens"] += 1
        else:
            counts["missing_registry_tokens"] += 1
        if not should_seed:
            continue
        if not args.apply:
            continue
        seed_orderfilled_registry_gap_snapshot(
            conn,
            token_id=summary.token_decimal or summary.token_hex,
            first_seen_block=summary.first_seen_block,
            last_seen_block=summary.last_seen_block,
            first_tx_hash=summary.first_tx_hash,
            last_tx_hash=summary.last_tx_hash,
            first_log_index=summary.first_log_index,
            last_log_index=summary.last_log_index,
            seen_count=summary.seen_count,
            sample_market_id=effective_market_id,
            note=note,
            commit=False,
            ensure_schema=False,
        )
        counts["seeded_open_gaps"] += 1
    if args.apply:
        conn.commit()
    if args.progress_every > 0 and counts["scanned_tokens"] % args.progress_every == 0:
        print(counts, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed historical OrderFilled registry gaps from ClickHouse history.")
    parser.add_argument("--postgres-host", default=os.environ.get("POLYDATA_POSTGRES_HOST", "127.0.0.1"))
    parser.add_argument("--postgres-port", type=int, default=int(os.environ.get("POLYDATA_POSTGRES_PORT", "45432")))
    parser.add_argument("--postgres-user", default=os.environ.get("POLYDATA_POSTGRES_USER", "poly_user"))
    parser.add_argument("--postgres-password", default=os.environ.get("POLYDATA_POSTGRES_PASSWORD", ""))
    parser.add_argument("--postgres-database", default=os.environ.get("POLYDATA_POSTGRES_DATABASE", "poly_data_core"))
    parser.add_argument("--clickhouse-container", default=os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_CONTAINER", "polydata_clickhouse_orderfilled"))
    parser.add_argument("--clickhouse-database", default=os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_DATABASE", "poly_orderfilled"))
    parser.add_argument("--clickhouse-user", default=os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_USER", "poly_user"))
    parser.add_argument("--clickhouse-password", default=os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_PASSWORD") or os.environ.get("CLICKHOUSE_PASSWORD", ""))
    parser.add_argument("--min-block", type=int, default=None)
    parser.add_argument("--max-block", type=int, default=None)
    parser.add_argument("--limit-tokens", type=int, default=0, help="Only scan the first N aggregated token ids for smoke tests.")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--progress-every", type=int, default=50000)
    parser.add_argument("--apply", action="store_true", help="Write OPEN gaps into ops.orderfilled_registry_gaps.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = seed_historical_gaps(args)
    print(summary)


if __name__ == "__main__":
    main()
