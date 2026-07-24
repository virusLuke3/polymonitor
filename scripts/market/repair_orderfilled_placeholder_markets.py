#!/usr/bin/env python3
"""Repair OrderFilled placeholder markets by refetching real market metadata.

This job intentionally repairs PostgreSQL market metadata first. It does not
mutate ClickHouse OrderFilled facts; those should be remapped only after the
token -> real market mapping has been reviewed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_ROOT.parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


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

from db import add_db_cli_args, configure_db_from_args, get_connection, init_schema
from market.market_discovery import fetch_and_upsert_markets_for_token_ids


DEFAULT_OUTPUT_DIR = Path(
    os.environ.get(
        "POLYDATA_PLACEHOLDER_MARKET_REPAIR_OUTPUT_DIR",
        str(REPO_ROOT / "artifacts" / "placeholder_market_repair"),
    )
)


@dataclass(frozen=True)
class PlaceholderToken:
    placeholder_market_id: int
    placeholder_condition_id: str
    token_id: str
    token_side: str
    created_at: str | None
    fact_rows: int = 0
    notional: float = 0.0


def shell_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def token_hex_to_decimal(value: Any) -> str:
    text = str(value or "").strip().lower().removeprefix("0x")
    if not text:
        return ""
    if text.isdigit():
        return text
    if re.fullmatch(r"[0-9a-f]{40,}", text):
        return str(int(text, 16))
    return ""


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def ch_cmd(args: argparse.Namespace, query: str) -> list[str]:
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


def ch_json(args: argparse.Namespace, query: str) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            ch_cmd(args, query.strip() + "\nFORMAT JSONEachRow"),
            text=True,
            capture_output=True,
            check=False,
            timeout=args.clickhouse_query_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"clickhouse-client timed out after {exc.timeout}s") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "clickhouse-client failed").strip()
        raise RuntimeError(f"clickhouse-client failed with exit code {proc.returncode}: {detail[:800]}")
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def fetch_placeholder_market_rows(args: argparse.Namespace, *, limit: int = 0) -> dict[int, dict[str, Any]]:
    init_schema(db_path=args.sqlite_path)
    sql = """
        SELECT
          m.id AS placeholder_market_id,
          m.condition_id AS placeholder_condition_id,
          m.yes_token_id AS yes_token_id,
          m.no_token_id AS no_token_id,
          m.created_at::text AS created_at
        FROM markets m
        WHERE (m.category = 'orderfilled-placeholder' OR m.slug LIKE 'trade-indexer-placeholder-%%')
          AND COALESCE(m.gamma_market_id, '') = ''
          AND COALESCE(m.event_id, '') = ''
        ORDER BY m.created_at DESC NULLS LAST, m.id DESC
    """
    params: tuple[Any, ...] = ()
    if limit > 0:
        sql += " LIMIT ?"
        params = (limit,)
    rows: dict[int, dict[str, Any]] = {}
    conn = get_connection(args.sqlite_path)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        for row in cur.fetchall():
            values = dict(row) if hasattr(row, "keys") else {
                "placeholder_market_id": row[0],
                "placeholder_condition_id": row[1],
                "yes_token_id": row[2],
                "no_token_id": row[3],
                "created_at": row[4],
            }
            rows[int(values["placeholder_market_id"])] = values
    finally:
        conn.close()
    return rows


def fetch_placeholder_tokens_from_clickhouse(args: argparse.Namespace) -> list[PlaceholderToken]:
    placeholders = fetch_placeholder_market_rows(args, limit=args.placeholder_scan_limit)
    if not placeholders:
        return []
    market_ids = sorted(placeholders)
    trade_rows: list[dict[str, Any]] = []
    for chunk in chunks(market_ids, args.clickhouse_market_batch_size):
        ids = ",".join(str(int(item)) for item in chunk)
        trade_rows.extend(
            ch_json(
                args,
                f"""
                SELECT
                    market_id,
                    token_id,
                    any(outcome_code) AS outcome_code,
                    count() AS fact_rows,
                    sum(toFloat64(price) * toFloat64(size)) AS notional
                FROM orderfilled_fact
                PREWHERE market_id IN ({ids})
                GROUP BY market_id, token_id
                """,
            )
        )
    candidates: dict[str, PlaceholderToken] = {}
    for row in trade_rows:
        market_id = int(row.get("market_id") or 0)
        placeholder = placeholders.get(market_id)
        if not placeholder:
            continue
        token_decimal = token_hex_to_decimal(row.get("token_id"))
        if not token_decimal:
            continue
        yes_token = str(placeholder.get("yes_token_id") or "").strip()
        no_token = str(placeholder.get("no_token_id") or "").strip()
        if token_decimal == yes_token:
            side = "YES"
        elif token_decimal == no_token and not no_token.startswith("unknown-complement-"):
            side = "NO"
        else:
            continue
        item = PlaceholderToken(
            placeholder_market_id=market_id,
            placeholder_condition_id=str(placeholder.get("placeholder_condition_id") or ""),
            token_id=token_decimal,
            token_side=side,
            created_at=placeholder.get("created_at"),
            fact_rows=int(row.get("fact_rows") or 0),
            notional=float(row.get("notional") or 0),
        )
        current = candidates.get(token_decimal)
        if current is None or (item.fact_rows, item.notional) > (current.fact_rows, current.notional):
            candidates[token_decimal] = item
    ordered = sorted(candidates.values(), key=lambda item: (item.fact_rows, item.notional), reverse=True)
    if args.limit > 0:
        ordered = ordered[: args.limit]
    return ordered


def fetch_placeholder_tokens(args: argparse.Namespace) -> list[PlaceholderToken]:
    explicit_tokens = [str(item).strip() for item in (args.token_id or []) if str(item).strip()]
    explicit_tokens.extend(read_token_file(args.token_file))
    if explicit_tokens:
        return [
            PlaceholderToken(
                placeholder_market_id=0,
                placeholder_condition_id="",
                token_id=token,
                token_side="UNKNOWN",
                created_at=None,
            )
            for token in dict.fromkeys(explicit_tokens)
        ]

    if args.source == "clickhouse":
        return fetch_placeholder_tokens_from_clickhouse(args)

    rows = fetch_placeholder_market_rows(args, limit=args.limit)
    out: list[PlaceholderToken] = []
    for values in rows.values():
        yes_token = str(values.get("yes_token_id") or "").strip()
        no_token = str(values.get("no_token_id") or "").strip()
        if yes_token:
            out.append(
                PlaceholderToken(
                    int(values["placeholder_market_id"]),
                    str(values["placeholder_condition_id"] or ""),
                    yes_token,
                    "YES",
                    values.get("created_at"),
                )
            )
        if no_token and not no_token.startswith("unknown-complement-"):
            out.append(
                PlaceholderToken(
                    int(values["placeholder_market_id"]),
                    str(values["placeholder_condition_id"] or ""),
                    no_token,
                    "NO",
                    values.get("created_at"),
                )
            )
    dedup: dict[str, PlaceholderToken] = {}
    for item in out:
        dedup.setdefault(item.token_id, item)
    return list(dedup.values())


def read_token_file(path: Path | None) -> list[str]:
    if not path:
        return []
    text = path.read_text(errors="ignore").strip()
    if not text:
        return []
    tokens: list[str] = []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = payload.get("tokens") or payload.get("token_ids") or payload.get("unresolved_tokens") or []
    else:
        candidates = re.split(r"[\s,]+", text)
    for item in candidates:
        token = str(item or "").strip()
        if token:
            tokens.append(token)
    return list(dict.fromkeys(tokens))


def find_non_placeholder_matches(args: argparse.Namespace, tokens: list[str]) -> list[dict[str, Any]]:
    if not tokens:
        return []
    matches: list[dict[str, Any]] = []
    chunk_size = 500
    conn = get_connection(args.sqlite_path)
    try:
        cur = conn.cursor()
        for start in range(0, len(tokens), chunk_size):
            chunk = tokens[start : start + chunk_size]
            placeholders = ",".join(["?"] * len(chunk))
            cur.execute(
                f"""
                SELECT id, gamma_market_id, condition_id, slug, title, category, yes_token_id, no_token_id, clob_token_ids
                FROM markets
                WHERE COALESCE(category, '') <> 'orderfilled-placeholder'
                  AND (
                    yes_token_id IN ({placeholders})
                    OR no_token_id IN ({placeholders})
                    OR EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements_text(clob_token_ids) AS token(value)
                      WHERE token.value IN ({placeholders})
                    )
                  )
                """,
                tuple(chunk + chunk + chunk),
            )
            rows = cur.fetchall()
            for row in rows:
                matches.append(dict(row) if hasattr(row, "keys") else dict(row))
    finally:
        conn.close()
    return matches


def repair(args: argparse.Namespace) -> dict[str, Any]:
    placeholders = fetch_placeholder_tokens(args)
    tokens = [item.token_id for item in placeholders]
    before_matches = find_non_placeholder_matches(args, tokens)
    upserted = 0
    if tokens and not args.dry_run:
        if args.skip_onchain:
            os.environ["POLYDATA_MARKET_BACKFILL_SKIP_ONCHAIN"] = "1"
        for start in range(0, len(tokens), args.token_batch_size):
            batch = tokens[start : start + args.token_batch_size]
            upserted += int(
                fetch_and_upsert_markets_for_token_ids(
                    batch,
                    db_path=args.sqlite_path,
                    max_pages=args.max_event_pages,
                    requests_delay=args.request_delay,
                )
                or 0
            )
    after_matches = find_non_placeholder_matches(args, tokens)
    matched_tokens = set()
    token_to_placeholder = {item.token_id: item for item in placeholders}
    for match in after_matches:
        for key in ("yes_token_id", "no_token_id"):
            token = str(match.get(key) or "")
            if token in token_to_placeholder:
                matched_tokens.add(token)
        raw_clob = match.get("clob_token_ids")
        clob_tokens: list[str] = []
        if isinstance(raw_clob, list):
            clob_tokens = [str(item) for item in raw_clob]
        elif raw_clob:
            try:
                clob_tokens = [str(item) for item in json.loads(str(raw_clob))]
            except Exception:
                clob_tokens = []
        matched_tokens.update(token for token in clob_tokens if token in token_to_placeholder)
    return {
        "dry_run": args.dry_run,
        "placeholder_tokens_scanned": len(tokens),
        "non_placeholder_matches_before": len(before_matches),
        "upserted_markets": upserted,
        "non_placeholder_matches_after": len(after_matches),
        "matched_placeholder_tokens_after": len(matched_tokens),
        "unmatched_placeholder_tokens_after": len(tokens) - len(matched_tokens),
        "sample_placeholders": [asdict(item) for item in placeholders[: args.output_sample_limit]],
        "sample_matches_after": after_matches[: args.output_sample_limit],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_db_cli_args(parser)
    parser.set_defaults(backend="postgres")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--source",
        choices=("clickhouse", "postgres"),
        default="clickhouse",
        help="clickhouse prioritizes placeholder tokens that actually appear in orderfilled_fact.",
    )
    parser.add_argument("--placeholder-scan-limit", type=int, default=0)
    parser.add_argument("--clickhouse-market-batch-size", type=int, default=1000)
    parser.add_argument("--clickhouse-query-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--clickhouse-container", default=os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_CONTAINER", "polydata_clickhouse_orderfilled"))
    parser.add_argument("--clickhouse-database", default=os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_DATABASE", "poly_orderfilled"))
    parser.add_argument("--clickhouse-user", default=os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_USER", "poly_user"))
    parser.add_argument("--clickhouse-password", default=os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_PASSWORD") or os.environ.get("CLICKHOUSE_PASSWORD", ""))
    parser.add_argument(
        "--token-id",
        action="append",
        default=[],
        help="Repair a specific CLOB token id; can be passed multiple times. When set, --limit is ignored.",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        help="Read token ids from a newline/comma separated file or JSON list/object.",
    )
    parser.add_argument("--token-batch-size", type=int, default=50)
    parser.add_argument("--max-event-pages", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument(
        "--skip-onchain",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip RPC/on-chain fallback while repairing placeholders; keeps historical repair quota-safe by default.",
    )
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-sample-limit", type=int, default=25)
    args = parser.parse_args()
    configure_db_from_args(args)
    if args.source == "clickhouse" and not args.clickhouse_password:
        raise SystemExit("CLICKHOUSE_PASSWORD or POLYDATA_ORDERFILLED_CLICKHOUSE_PASSWORD is required for --source clickhouse")
    return args


def main() -> int:
    args = parse_args()
    payload = {
        "script": "repair_orderfilled_placeholder_markets",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "result": repair(args),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"placeholder_market_repair_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    payload["output_path"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
