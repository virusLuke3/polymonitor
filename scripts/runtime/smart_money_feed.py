"""Replay committed Smart Money trades using the worktree's own signal builder."""

import json
import sys
from pathlib import Path

from api.services.smart_money_signals_service import public_card
from smart_money.bootstrap.paths import load_environment
from smart_money.infrastructure.trade_storage import connect_trades, signal_trades
from smart_money.signals import group_signals


PAGE_SIZE = 1000


def read_feed(cursor, pending):
    load_environment()
    with connect_trades() as db, db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        db.execute("SET LOCAL statement_timeout='8s'")
        if cursor is None:
            # The worktree serializes trade writes with monitor.lock. An in-flight
            # wallet write can predate this read, so use its last committed row.
            since = db.execute("SELECT observed_at,id FROM trades ORDER BY observed_at DESC,id DESC LIMIT 1").fetchone()
            cursor = [since["observed_at"].isoformat(), since["id"]] if since else ["1970-01-01T00:00:00+00:00", ""]
            pending = [row["id"] for row in db.execute("SELECT id FROM trades WHERE status='PENDING_REVIEW'")]
            return {"cursor": cursor, "pending": pending, "items": [], "rows": 0}

        rows = db.execute(
            "SELECT id,observed_at,status FROM trades WHERE (observed_at,id)>(%s::timestamptz,%s) "
            "ORDER BY observed_at,id LIMIT %s", (*cursor, PAGE_SIZE),
        ).fetchall()
        promoted = {row["id"] for row in db.execute(
            "SELECT id FROM trades WHERE id=ANY(%s) AND status='MATCHED'", (pending,),
        )}
        matched = promoted | {row["id"] for row in rows if row["status"] == "MATCHED"}
        pending = sorted((set(pending) - promoted) | {row["id"] for row in rows if row["status"] == "PENDING_REVIEW"})
        if rows:
            cursor = [rows[-1]["observed_at"].isoformat(), rows[-1]["id"]]
        records = signal_trades(db, trade_ids=matched) if matched else []
    watchlist = Path("var/wallet_watchlist.json")
    selection = json.loads(watchlist.read_bytes()) if watchlist.exists() else None
    signals = group_signals(records, selection, trade_ids=matched)
    return {"cursor": cursor, "pending": pending, "items": [public_card(row) for row in signals], "rows": len(rows)}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(read_feed(request.get("cursor"), request.get("pending", [])), ensure_ascii=False))
