"""Batch runner primitives for quant price builds.

The runner is intentionally inert on import. Use the module CLI for one-shot
jobs; daemon/watch wiring should live in a later deployment step.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from .block_close_backfill import backfill_block_close_prices
from .db import ClickHouseClient, PostgresSettings, postgres_connection
from .eligibility import refresh_eligibility
from .frontend_backfill import backfill_frontend_prices
from .frontend_client import FrontendPriceClient
from .metadata import refresh_market_token_metadata
from .schema import create_schema


def start_run(conn: Any, *, source: str, mode: str, meta: dict[str, Any]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO quant.market_price_build_runs (source, mode, status, meta)
            VALUES (%s, %s, 'running', %s::jsonb)
            RETURNING run_id
            """,
            (source, mode, json.dumps(meta, sort_keys=True)),
        )
        row = cur.fetchone()
        return int(row["run_id"])


def finish_run(conn: Any, *, run_id: int, status: str, rows_written: int, markets_complete: int, error_count: int = 0, last_error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quant.market_price_build_runs
            SET status = %s,
                finished_at = now(),
                rows_written = %s,
                markets_complete = %s,
                error_count = %s,
                last_error = %s
            WHERE run_id = %s
            """,
            (status, rows_written, markets_complete, error_count, last_error, run_id),
        )


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    with postgres_connection(PostgresSettings()) as conn:
        create_schema(conn)
        if args.refresh_metadata:
            refresh_market_token_metadata(conn)
        if args.refresh_eligibility:
            refresh_eligibility(conn, ClickHouseClient())

        meta = vars(args).copy()
        run_id = start_run(conn, source=args.source, mode="once", meta=meta)
        try:
            if args.source == "frontend":
                result = backfill_frontend_prices(
                    conn,
                    FrontendPriceClient(),
                    start_ts=args.start_ts,
                    end_ts=args.end_ts,
                    fidelity_minutes=args.fidelity_minutes,
                    limit=args.limit,
                )
            elif args.source == "orderfilled_block_close":
                result = backfill_block_close_prices(
                    conn,
                    ClickHouseClient(),
                    from_block=args.from_block,
                    to_block=args.to_block,
                    limit=args.limit,
                )
            else:
                raise ValueError(f"unsupported source: {args.source}")
            finish_run(
                conn,
                run_id=run_id,
                status="complete",
                rows_written=int(result.get("rows_written") or 0),
                markets_complete=int(result.get("tokens") or 0),
                error_count=int(result.get("failures") or 0),
            )
            result["run_id"] = run_id
            return result
        except Exception as exc:
            finish_run(conn, run_id=run_id, status="error", rows_written=0, markets_complete=0, error_count=1, last_error=repr(exc))
            conn.commit()
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a one-shot quant price build.")
    parser.add_argument("--source", choices=("frontend", "orderfilled_block_close"), required=True)
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--refresh-eligibility", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-ts", type=int)
    parser.add_argument("--end-ts", type=int)
    parser.add_argument("--fidelity-minutes", type=int, default=1)
    parser.add_argument("--from-block", type=int)
    parser.add_argument("--to-block", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.source == "frontend" and (args.start_ts is None or args.end_ts is None):
        raise SystemExit("--start-ts and --end-ts are required for frontend")
    if args.source == "orderfilled_block_close" and (args.from_block is None or args.to_block is None):
        raise SystemExit("--from-block and --to-block are required for orderfilled_block_close")
    print(run_once(args))


if __name__ == "__main__":
    main()
