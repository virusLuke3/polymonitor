#!/usr/bin/env python3
"""Evaluate product watchlist rules without coupling delivery to Telegram."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.services.product_service import evaluate_alert_rules, record_alert_runtime_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Evaluate once and exit.")
    mode.add_argument("--watch", action="store_true", help="Continue evaluating until stopped.")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("POLYDATA_PRODUCT_ALERT_INTERVAL_SECONDS", "60")),
        help="Seconds between evaluations in watch mode.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    interval = max(15, args.interval)
    watch = args.watch and not args.once
    while True:
        started = time.monotonic()
        try:
            result = evaluate_alert_rules()
            logging.info("product-alert-evaluation %s", json.dumps(result, sort_keys=True))
        except Exception as error:
            logging.exception("product-alert-evaluation failed")
            try:
                record_alert_runtime_error(error)
            except Exception:
                logging.exception("could not persist product-alert runtime error")
            if not watch:
                return 1
        if not watch or stopping:
            return 0
        deadline = time.monotonic() + max(1, interval - (time.monotonic() - started))
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1, deadline - time.monotonic()))


if __name__ == "__main__":
    raise SystemExit(main())
