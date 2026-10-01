#!/usr/bin/env python3
"""The existing content worker now ingests only the reviewed free-source allowlist."""

from __future__ import annotations
import argparse, fcntl, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    parser = argparse.ArgumentParser(description="Free public content on the existing content pipeline")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--probe", action="store_true", help="Live transport/parse/policy probe; no content writes")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--sources", default="")
    parser.add_argument(
        "--force", action="store_true", help="Run once even when not due; 429 Retry-After still applies"
    )
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--topics", default="", help=argparse.SUPPRESS)
    parser.add_argument("--limit-per-topic", type=int, default=24, help=argparse.SUPPRESS)
    parser.add_argument("--list-topics", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    from api.runtime import ServiceRuntime
    from api.services.query_service import ContentStorageDependencies
    from api.services.free_content.collector import cycle
    from api.services.free_content.store import source_states
    from api.services.free_content.registry import sources
    from api.services.free_content.snapshots import refresh_candidates, NAMESPACE, CACHE_KEY
    from api.cache import get_redis_client
    from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, utc_now_iso

    if args.list_topics:
        print(json.dumps(sources(), ensure_ascii=False))
        return 0
    with ServiceRuntime() as runtime:
        storage = ContentStorageDependencies.from_context(runtime.query_context)
        if args.status:
            print(json.dumps(source_states(storage), ensure_ascii=False, indent=2, default=str))
            return 0
        fd = runtime._try_acquire_runtime_lock("content-topic-refresh.lock")
        if fd is None:
            print("Content worker already owns the shared lock.", file=sys.stderr)
            return 2
        owner = None
        if storage.get_backend() == "postgres":
            owner = runtime.SETTINGS.database.connect(connect_timeout=5)
            acquired = owner.execute(
                "SELECT pg_try_advisory_lock(hashtext('polymonitor_free_content_worker')) AS acquired"
            ).fetchone()["acquired"]
            owner.commit()
            if not acquired:
                owner.close()
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                print("Another host owns the database content-worker lock.", file=sys.stderr)
                return 2
        try:
            while True:
                for result in cycle(
                    storage,
                    runtime.SNAPSHOT_STORE,
                    probe=args.probe,
                    force=args.force,
                    selected=set(filter(None, args.sources.split(","))) or None,
                ):
                    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
                if not args.probe:
                    meta_store = SeedMetaStore(redis_client=get_redis_client(runtime.cache),
                        redis_prefix=runtime.SETTINGS.redis_prefix, snapshot_store=runtime.SNAPSHOT_STORE)
                    prior = meta_store.load("seed-meta:content", "related-news") or {}
                    attempted = utc_now_iso()
                    try:
                        seed = refresh_candidates(storage, runtime.query_context["free_content_cache"], require_cache=True)
                        meta = build_seed_meta_payload(panel_id="related-news", namespace="seed-meta:content",
                            cache_key="related-news", service_name="polydata-content-topic-refresh.service",
                            expected_interval_seconds=max(30, min(60, args.interval)), status="ready",
                            last_attempt_at=attempted, last_success_at=seed["generatedAt"],
                            record_count=sum(r["record_kind"] == "item" for r in seed["records"]),
                            source_states=source_states(storage), cache_mode="seeded",
                            metadata={"candidateNamespace": NAMESPACE, "candidateKey": CACHE_KEY})
                    except Exception as exc:
                        meta = {**prior, "panelId": "related-news", "status": "error",
                                "lastAttemptAt": attempted, "lastSuccessAt": prior.get("lastSuccessAt"),
                                "errorSummary": type(exc).__name__}
                    meta_store.store("seed-meta:content", "related-news", meta)
                    print(json.dumps({"seed": "related-news", "status": meta["status"]}), flush=True)
                if not args.watch:
                    break
                time.sleep(max(30, min(60, args.interval)))
        finally:
            if owner is not None:
                owner.execute("SELECT pg_advisory_unlock(hashtext('polymonitor_free_content_worker'))")
                owner.commit()
                owner.close()
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
