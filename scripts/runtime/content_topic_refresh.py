#!/usr/bin/env python3
"""The existing content worker now ingests only the reviewed free-source allowlist."""

from __future__ import annotations
import argparse, fcntl, json, os, sys, time, multiprocessing, queue
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CYCLE_BUDGET_SECONDS = 90
SEED_HEARTBEAT_SECONDS = 30


def publish_seed(runtime, storage, interval, cycle_error=None):
    """Seed failure is observable and never stops the existing watch loop."""
    from api.cache import get_redis_client
    from api.services.free_content.snapshots import refresh_candidates, NAMESPACE, CACHE_KEY
    from api.services.free_content.store import source_states
    from api.services.free_content.registry import sources
    from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, utc_now_iso

    attempted = utc_now_iso()
    prior = {}
    meta_store = None
    try:
        meta_store = SeedMetaStore(redis_client=get_redis_client(runtime.cache),
            redis_prefix=runtime.SETTINGS.redis_prefix, snapshot_store=runtime.SNAPSHOT_STORE)
        prior = meta_store.load("seed-meta:content", "related-news") or {}
        seed = refresh_candidates(storage, runtime.query_context["free_content_cache"], require_cache=True)
        saved = source_states(storage)
        states = {source["source_id"]: saved.get(source["source_id"], {"status": "not_requested"})
                  for source in sources() if source.get("enabled")}
        degraded = cycle_error or any(s.get("status") not in {"ok", "unchanged", "healthy_empty"}
            or s.get("snapshot_stale") or (s.get("next_check_at") and s["next_check_at"] < attempted) for s in states.values())
        meta = build_seed_meta_payload(panel_id="related-news", namespace="seed-meta:content",
            cache_key="related-news", service_name="polydata-content-topic-refresh.service",
            expected_interval_seconds=max(30, min(60, interval)), status="degraded" if degraded else "ready",
            last_attempt_at=attempted, last_success_at=seed["generatedAt"],
            record_count=sum(r["record_kind"] == "item" for r in seed["records"]),
            source_states=states, cache_mode="seeded",
            metadata={"candidateNamespace": NAMESPACE, "candidateKey": CACHE_KEY, "cycleError": cycle_error})
    except Exception as exc:
        meta = {**prior, "panelId": "related-news", "status": "error",
                "lastAttemptAt": attempted, "lastSuccessAt": prior.get("lastSuccessAt"),
                "errorSummary": type(exc).__name__}
    if meta_store:
        try:
            meta_store.store("seed-meta:content", "related-news", meta)
        except Exception as exc:
            meta["metaWriteError"] = type(exc).__name__
    print(json.dumps({"seed": "related-news", **{key: meta.get(key) for key in
        ("status", "recordCount", "lastSuccessAt", "errorSummary", "metaWriteError")}, "cycleError": cycle_error}, default=str), flush=True)
    return meta


def _cycle_process(events, options):
    """Fresh runtime/connections: never inherit the parent worker's DB lock/session."""
    from api.runtime import ServiceRuntime
    from api.services.query_service import ContentStorageDependencies
    from api.services.free_content.collector import cycle
    try:
        with ServiceRuntime() as runtime:
            storage = ContentStorageDependencies.from_context(runtime.query_context)
            cycle(storage, runtime.SNAPSHOT_STORE, **options,
                  on_result=lambda state: events.put({"result": state}))
    except Exception as exc:
        events.put({"cycleError": type(exc).__name__})


def run_bounded_cycle(runtime, storage, *, probe=False, force=False, selected=None, interval=60,
                      budget=CYCLE_BUDGET_SECONDS):
    from api.services.free_content.collector import due_sources
    from api.services.free_content.store import source_states, save_state
    old = source_states(storage)
    pending = due_sources(old, probe=probe, force=force, selected=selected)
    if not probe:
        publish_seed(runtime, storage, interval)
    if not pending:
        return None
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    process = context.Process(target=_cycle_process, args=(events, {"probe": probe, "force": force,
        "selected": {source["source_id"] for source in pending}}))
    completed = set()
    error = None
    started = time.monotonic()
    heartbeat = started
    process.start()
    try:
        while process.is_alive():
            if time.monotonic() - started >= budget:
                error = "cycle-budget-exhausted"
                process.terminate()
                process.join(timeout=3)
                if process.is_alive():
                    process.kill()
                break
            try:
                event = events.get(timeout=min(0.5, max(0.01, budget - (time.monotonic() - started))))
                if event.get("result"):
                    completed.add(event["result"]["source_id"])
                    print(json.dumps(event["result"], default=str), flush=True)
                error = event.get("cycleError") or error
            except queue.Empty:
                pass
            if not probe and time.monotonic() - heartbeat >= SEED_HEARTBEAT_SECONDS:
                publish_seed(runtime, storage, interval, error)
                heartbeat = time.monotonic()
        process.join(timeout=3)
        while process.exitcode == 0:
            try:
                event = events.get_nowait()
                if event.get("result"):
                    completed.add(event["result"]["source_id"])
                    print(json.dumps(event["result"], default=str), flush=True)
                error = event.get("cycleError") or error
            except queue.Empty:
                break
        if process.exitcode and not error:
            error = "cycle-process-failed"
        if error and not probe:
            now = datetime.now(timezone.utc)
            for source in pending:
                sid = source["source_id"]
                if sid in completed:
                    continue
                try:
                    save_state(storage, sid, {**old.get(sid, {}), "source_id": sid, "status": "error",
                        "checked_at": now.isoformat().replace("+00:00", "Z"), "error": error,
                        "next_check_at": (now + timedelta(seconds=source["poll_interval_seconds"])).isoformat().replace("+00:00", "Z")})
                except Exception as exc:
                    print(json.dumps({"source_id": sid, "error": "state-write-failed:" + type(exc).__name__}), flush=True)
    finally:
        if process.is_alive():
            process.kill(); process.join(timeout=3)
        events.cancel_join_thread(); events.close()
    if not probe:
        publish_seed(runtime, storage, interval, error)
    return error


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
    from api.services.free_content.store import source_states, ensure_schema
    from api.services.free_content.registry import sources

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
            ensure_schema(storage)
            while True:
                try:
                    cycle_error = run_bounded_cycle(runtime, storage, probe=args.probe, force=args.force,
                        selected=set(filter(None, args.sources.split(","))) or None, interval=args.interval)
                except Exception as exc:
                    cycle_error = type(exc).__name__
                    if not args.probe:
                        publish_seed(runtime, storage, args.interval, cycle_error)
                if not args.watch:
                    return 1 if cycle_error else 0
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
