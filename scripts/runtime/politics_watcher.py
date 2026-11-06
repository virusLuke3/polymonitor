"""Independent owners: one slow provider does not block other political sources."""
import argparse
import os
from api.services.politics.collector import collect_owner
from runtime.snapshot_store import SnapshotStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, choices=["elections", "campaign-finance", "government"])
    args = parser.parse_args()
    collect_owner(SnapshotStore(os.environ["POLYDATA_SNAPSHOT_SQLITE_PATH"]), args.owner)


if __name__ == "__main__":
    main()
