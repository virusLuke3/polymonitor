#!/usr/bin/env python3
"""Aggregate an existing labeled BTC archive without changing its research status."""
import argparse
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def export(source, output):
    source, output = Path(source), Path(output)
    manifest = json.loads((source / "manifest.json").read_text())
    totals = defaultdict(lambda: {"inflow": Decimal(0), "outflow": Decimal(0), "net": Decimal(0), "transactions": 0})
    count = 0
    with (source / "transaction_flows.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            key = (row["block_date"], row["cex_name"])
            target = totals[key]
            for field in ("inflow", "outflow", "net"):
                value = Decimal(row[field + "_flow_btc"] if field == "net" else row[field + "_btc"])
                if not value.is_finite():
                    raise ValueError("nonfinite flow")
                target[field] += value
            target["transactions"] += 1
            count += 1
    if count != manifest["counts"]["transaction_flows"]:
        raise ValueError("archive row count mismatch")
    rows = [{"date": date, "exchange": exchange, **{key: float(v) if isinstance(v, Decimal) else v for key, v in values.items()}}
        for (date, exchange), values in sorted(totals.items())]
    payload = {"schemaVersion": 1, "mode": "historical", "asset": "BTC", "unit": "BTC", "rows": rows,
        "source": "Dune Bitcoin labeled exchange transfer archive", "datasetId": manifest["dataset_id"],
        "sourceManifestSha256": hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest(),
        "coverage": manifest["observed_coverage"], "labelSemantics": "LATER_RETRIEVED_LABEL_SNAPSHOT",
        "liveAvailable": False, "strictPitApproved": False, "transactions": count,
        "limitations": ["Retrospective address labels; research only", "Matched transfer legs; internal transfers may remain; inflow is not a sale"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, allow_nan=False))
    temporary.replace(output)
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print("Exported daily exchange rows:", export(args.source, args.output))
