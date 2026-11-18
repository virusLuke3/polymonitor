"""Forward the saved Smart Money stream with a checkpoint and per-card receipts."""

import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from requests.exceptions import ConnectTimeout

from .client import SAFE_TEXT_LENGTH, TelegramSendRejected
from .formatters import format_smart_money_signals


SMART_MONEY = "alpha-signal"
SOURCE_ENV = ("POLYMONITOR_SMART_MONEY_WORKTREE", "POLYMONITOR_SMART_MONEY_PYTHON", "POLYMONITOR_SMART_MONEY_ENV_FILE")
HEADER = "🧠 Smart Money · Alpha Signal"
SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK (id=1), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS delivery (
    signal_id TEXT PRIMARY KEY, trade_at REAL NOT NULL, attempted_at REAL NOT NULL,
    message_id INTEGER, telegram_at INTEGER
);
"""


def _packets(cards):
    markets = defaultdict(list)
    for card in cards:
        markets[card.metadata["market"]].append(card)

    body, members, last_market = HEADER, [], None
    for market, entries in markets.items():
        title, url, reasons = market
        heading = "\n\n" + "\n".join(filter(None, (title, url, reasons)))
        for card in entries:
            line = "\n" + card.metadata["line"]
            extra = line if market == last_market else heading + line
            if members and len((body + extra).encode("utf-16-le")) // 2 > SAFE_TEXT_LENGTH:
                yield body, members
                body, members, extra = HEADER, [], heading + line
            body += extra
            members.append(card)
            last_market = market
    if members:
        yield body, members


def relay(settings, state, telegram):
    if not settings.alpha.enabled or not all(os.environ.get(key) for key in SOURCE_ENV):
        return {}

    from scripts.api.services.smart_money_signals_service import run_source

    path = Path(settings.state_path).expanduser().with_suffix(".smart-money.sqlite3")
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        saved = db.execute("SELECT data FROM checkpoint WHERE id=1").fetchone()
        request = json.loads(saved[0]) if saved else {}
        page = json.loads(run_source("-m", "runtime.smart_money_feed", include_runtime=True, input_data=json.dumps(request)))
        cards = format_smart_money_signals({"source": "matched-trades-v2", "status": "ok", "items": page["items"]})
        if len(cards) != len(page["items"]):
            raise ValueError("Inconsistent Smart Money card data")

        ready, uncertain, seen = [], 0, 0
        for card in cards:
            record = db.execute("SELECT message_id FROM delivery WHERE signal_id=?", (card.dedupe_key,)).fetchone()
            legacy = state.payload["sent"].get("alpha:" + card.dedupe_key)
            if record is None and legacy is None:
                ready.append(card)
            elif (record and record[0] is not None) or (legacy and legacy.get("messageId")):
                seen += 1
            else:
                uncertain += 1

        sent, messages, failures = 0, 0, 0
        for text, members in _packets(ready):
            if len(text.encode("utf-16-le")) // 2 > SAFE_TEXT_LENGTH:
                raise ValueError("Smart Money market line exceeds Telegram message capacity")
            attempted = time.time()
            keys = [(card.dedupe_key,) for card in members]
            with db:
                db.executemany("INSERT INTO delivery(signal_id,trade_at,attempted_at) VALUES (?,?,?)", (
                    (card.dedupe_key, card.observed_at, attempted) for card in members
                ))
            try:
                (response,) = telegram.send_message(
                    chat_id=settings.alpha.chat_id, message_thread_id=settings.alpha.message_thread_id,
                    text=text, disable_notification=settings.disable_notification,
                )
                receipt = response["result"]
                message_id, telegram_at = receipt["message_id"], receipt["date"]
            except (ConnectTimeout, TelegramSendRejected) as exc:
                with db:
                    db.executemany("DELETE FROM delivery WHERE signal_id=?", keys)
                failures += 1
                print(f"[telegram-publisher] Smart Money send rejected error_class={type(exc).__name__}", file=sys.stderr)
                break
            except Exception as exc:
                uncertain += len(members)
                print(f"[telegram-publisher] Smart Money delivery unconfirmed error_class={type(exc).__name__}", file=sys.stderr)
                break
            with db:
                db.executemany("UPDATE delivery SET message_id=?,telegram_at=? WHERE signal_id=?", (
                    (message_id, telegram_at, card.dedupe_key) for card in members
                ))
            sent += len(members)
            messages += 1

        if not failures and not uncertain:
            with db:
                db.execute("INSERT INTO checkpoint VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (
                    json.dumps({"cursor": page["cursor"], "pending": page["pending"]}),
                ))
        return {"rows": page["rows"], "cards": len(cards), "sent": sent, "messages": messages,
                "seen": seen, "uncertain": uncertain, "failures": failures}
