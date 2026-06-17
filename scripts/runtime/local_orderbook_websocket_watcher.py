#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_scripts_root = Path(__file__).resolve().parents[1]
_project_root = _scripts_root.parent
for _path in (str(_project_root), str(_scripts_root)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    import fcntl
except ImportError:  # pragma: no cover - non-posix fallback.
    fcntl = None

try:
    import websockets
except ImportError:  # pragma: no cover - dependency guard.
    websockets = None

from api.services import lob_service
from data_sources import POLYMARKET_CLOB_WS_URL
from quant.orderbook import OrderBookNotReady, OrderBookOutOfOrder, TokenBookIdentity, normalize_polymarket_event


DEFAULT_COVERAGE_LIMIT = 250
DEFAULT_COVERAGE_TOPICS = "worldcup,crypto,politics"
DEFAULT_COVERAGE_REFRESH_SECONDS = 300
DEFAULT_RECONNECT_SECONDS = 5
DEFAULT_SUBSCRIPTION_BATCH_SIZE = 200
DEFAULT_FALLBACK_SAMPLE_INTERVAL_SECONDS = 60
DEFAULT_BOOTSTRAP_MARKET_LIMIT = 6
DEFAULT_LOCK_NAME = "local-orderbook-websocket.worker.lock"


@dataclass(frozen=True)
class CoverageTarget:
    market_id: int
    market_slug: str
    market_title: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    topic: str
    tier: str
    sample_interval_seconds: int
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, item: dict[str, Any]) -> "CoverageTarget | None":
        market_id = _int_or_none(item.get("marketId") or item.get("market_id"))
        yes_token_id = str(item.get("yesTokenId") or item.get("yes_token_id") or "").strip()
        no_token_id = str(item.get("noTokenId") or item.get("no_token_id") or "").strip()
        if market_id is None or not yes_token_id or not no_token_id:
            return None
        return cls(
            market_id=market_id,
            market_slug=str(item.get("marketSlug") or item.get("market_slug") or ""),
            market_title=str(item.get("marketTitle") or item.get("market_title") or ""),
            condition_id=str(item.get("conditionId") or item.get("condition_id") or ""),
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            topic=str(item.get("topic") or ""),
            tier=str(item.get("tier") or ""),
            sample_interval_seconds=max(1, int(_int_or_none(item.get("sampleIntervalSeconds")) or DEFAULT_FALLBACK_SAMPLE_INTERVAL_SECONDS)),
            raw=dict(item),
        )

    def identities(self) -> tuple[TokenBookIdentity, TokenBookIdentity]:
        return (
            TokenBookIdentity(
                token_id=self.yes_token_id,
                market_id=self.market_id,
                condition_id=self.condition_id,
                outcome="YES",
                outcome_index=0,
                market_slug=self.market_slug or None,
            ),
            TokenBookIdentity(
                token_id=self.no_token_id,
                market_id=self.market_id,
                condition_id=self.condition_id,
                outcome="NO",
                outcome_index=1,
                market_slug=self.market_slug or None,
            ),
        )

    @property
    def token_ids(self) -> tuple[str, str]:
        return self.yes_token_id, self.no_token_id


class _Logger:
    def info(self, message: str, *args: Any) -> None:
        print(f"[local-orderbook-ws] INFO {message % args if args else message}", file=sys.stderr)

    def warning(self, message: str, *args: Any) -> None:
        print(f"[local-orderbook-ws] WARN {message % args if args else message}", file=sys.stderr)

    def exception(self, message: str, *args: Any) -> None:
        print(f"[local-orderbook-ws] ERROR {message % args if args else message}", file=sys.stderr)


class LocalOrderBookWebsocketWatcher:
    def __init__(
        self,
        *,
        ctx: dict[str, Any],
        ws_url: str,
        limit: int = DEFAULT_COVERAGE_LIMIT,
        topics: str = DEFAULT_COVERAGE_TOPICS,
        coverage_refresh_seconds: int = DEFAULT_COVERAGE_REFRESH_SECONDS,
        subscription_batch_size: int = DEFAULT_SUBSCRIPTION_BATCH_SIZE,
        bootstrap_market_limit: int = DEFAULT_BOOTSTRAP_MARKET_LIMIT,
        persist: bool = True,
        bootstrap: bool = True,
        logger: Any | None = None,
    ) -> None:
        if websockets is None:
            raise RuntimeError("websockets package is required. Install scripts/requirements.txt")
        self.ctx = ctx
        self.manager = ctx["LOB_RUNTIME_MANAGER"]
        self.ws_url = str(ws_url or "").strip()
        if not self.ws_url:
            raise RuntimeError("POLYDATA_CLOB_WS_URL is required for LocalOrderBook websocket watcher")
        self.limit = max(1, min(int(limit or DEFAULT_COVERAGE_LIMIT), 500))
        self.topics = str(topics or DEFAULT_COVERAGE_TOPICS)
        self.coverage_refresh_seconds = max(30, int(coverage_refresh_seconds or DEFAULT_COVERAGE_REFRESH_SECONDS))
        self.subscription_batch_size = max(1, min(int(subscription_batch_size or DEFAULT_SUBSCRIPTION_BATCH_SIZE), 500))
        self.bootstrap_market_limit = max(0, int(bootstrap_market_limit if bootstrap_market_limit is not None else DEFAULT_BOOTSTRAP_MARKET_LIMIT))
        self.persist = bool(persist)
        self.bootstrap = bool(bootstrap)
        self.logger = logger or _Logger()
        self.targets_by_market: dict[int, CoverageTarget] = {}
        self.identities_by_token: dict[str, TokenBookIdentity] = {}
        self.target_by_token: dict[str, CoverageTarget] = {}
        self.subscribed_tokens: set[str] = set()
        self._last_persisted_at_by_market: dict[int, float] = {}
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def refresh_targets(self) -> list[CoverageTarget]:
        payload = lob_service.get_lob_coverage_targets_payload(self.ctx, limit=self.limit, topics=self.topics)
        if payload.get("_status") or payload.get("error"):
            raise RuntimeError(str(payload.get("detail") or payload.get("error") or "coverage target selection failed"))
        targets = [
            target
            for target in (CoverageTarget.from_payload(item) for item in (payload.get("items") or []))
            if target is not None
        ]
        self.targets_by_market = {target.market_id: target for target in targets}
        self.identities_by_token = {}
        self.target_by_token = {}
        for target in targets:
            yes_identity, no_identity = target.identities()
            self.identities_by_token[yes_identity.token_id] = yes_identity
            self.identities_by_token[no_identity.token_id] = no_identity
            self.target_by_token[yes_identity.token_id] = target
            self.target_by_token[no_identity.token_id] = target
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        self.logger.info("coverage refreshed markets=%s tokens=%s topics=%s", len(targets), len(self.identities_by_token), summary.get("topics"))
        return targets

    def bootstrap_targets(self, targets: Iterable[CoverageTarget] | None = None, *, force_refresh: bool = False) -> int:
        if not self.bootstrap:
            return 0
        count = 0
        for target in targets if targets is not None else self.targets_by_market.values():
            try:
                self.manager.get_market_snapshot(
                    market_id=target.market_id,
                    yes_token_id=target.yes_token_id,
                    no_token_id=target.no_token_id,
                    market_title=target.market_title,
                    condition_id=target.condition_id,
                    market_slug=target.market_slug or None,
                    force_refresh=force_refresh,
                )
                count += 1
                self.persist_target_if_due(target, force=True, reason="bootstrap")
            except Exception as exc:
                self.logger.warning("bootstrap failed market_id=%s title=%s error=%s", target.market_id, target.market_title[:80], exc)
        if count:
            self.logger.info("bootstrap complete markets=%s", count)
        return count

    async def run_forever(self) -> None:
        reconnect_seconds = max(1, int(os.environ.get("POLYDATA_LOB_WS_RECONNECT_SECONDS", DEFAULT_RECONNECT_SECONDS) or DEFAULT_RECONNECT_SECONDS))
        while not self._stop_event.is_set():
            try:
                await self.run_connection()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.warning("websocket connection failed: %s", exc)
                await asyncio.sleep(reconnect_seconds)

    async def run_connection(self, *, run_seconds: int | None = None) -> None:
        targets = self.refresh_targets()
        self.bootstrap_targets(targets[: self.bootstrap_market_limit] if self.bootstrap_market_limit else [], force_refresh=True)
        deadline = time.monotonic() + run_seconds if run_seconds and run_seconds > 0 else None
        last_refresh_at = time.monotonic()
        async with websockets.connect(self.ws_url, ping_interval=None, close_timeout=10, max_queue=1000) as websocket:
            await self.subscribe(websocket, sorted(self.identities_by_token), replace=True)
            self.logger.info("connected subscribed_tokens=%s", len(self.subscribed_tokens))
            while not self._stop_event.is_set():
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    break
                if now - last_refresh_at >= self.coverage_refresh_seconds:
                    await self.reconcile_subscriptions(websocket)
                    last_refresh_at = now
                timeout = 5.0
                if deadline is not None:
                    timeout = max(0.1, min(timeout, deadline - now))
                try:
                    raw_message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    continue
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8")
                await self.handle_raw_message(str(raw_message))

    async def reconcile_subscriptions(self, websocket: Any) -> None:
        previous = set(self.subscribed_tokens)
        targets = self.refresh_targets()
        desired = set(self.identities_by_token)
        added_targets = [target for target in targets if any(token_id not in previous for token_id in target.token_ids)]
        if added_targets:
            self.bootstrap_targets(added_targets, force_refresh=True)
        to_subscribe = sorted(desired - previous)
        to_unsubscribe = sorted(previous - desired)
        if to_subscribe:
            await self.subscribe(websocket, to_subscribe, replace=False)
        if to_unsubscribe:
            await self.unsubscribe(websocket, to_unsubscribe)
        if to_subscribe or to_unsubscribe:
            self.logger.info("reconciled subscribe_add=%s subscribe_remove=%s", len(to_subscribe), len(to_unsubscribe))

    async def subscribe(self, websocket: Any, token_ids: list[str], *, replace: bool) -> None:
        if not token_ids:
            return
        batches = list(_chunked(token_ids, self.subscription_batch_size))
        for index, batch in enumerate(batches):
            if replace and index == 0:
                payload = {"type": "market", "custom_feature_enabled": True, "assets_ids": batch}
            else:
                payload = {"operation": "subscribe", "custom_feature_enabled": True, "assets_ids": batch}
            await websocket.send(json.dumps(payload, ensure_ascii=True))
            self.subscribed_tokens.update(batch)

    async def unsubscribe(self, websocket: Any, token_ids: list[str]) -> None:
        for batch in _chunked(token_ids, self.subscription_batch_size):
            await websocket.send(json.dumps({"operation": "unsubscribe", "assets_ids": batch}, ensure_ascii=True))
            for token_id in batch:
                self.subscribed_tokens.discard(token_id)

    async def handle_raw_message(self, raw_message: str) -> None:
        if raw_message in {"PONG", "PING", ""}:
            return
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            self.logger.warning("ignoring non-json websocket message=%s", raw_message[:160])
            return
        for event in _iter_json_events(payload):
            self.handle_event(event)

    def handle_event(self, event: dict[str, Any]) -> int:
        changed_markets: set[int] = set()
        for normalized in normalize_polymarket_event(event):
            identity = self.identities_by_token.get(normalized.token_id)
            if identity is None:
                continue
            target = self.target_by_token.get(normalized.token_id)
            try:
                self.manager.apply_normalized_event(identity, normalized)
            except (OrderBookNotReady, OrderBookOutOfOrder):
                if target is not None:
                    self.bootstrap_targets([target], force_refresh=True)
                    changed_markets.add(target.market_id)
                continue
            if target is not None:
                changed_markets.add(target.market_id)
        for market_id in changed_markets:
            target = self.targets_by_market.get(market_id)
            if target is not None:
                self.persist_target_if_due(target, reason=str(event.get("event_type") or "websocket"))
        return len(changed_markets)

    def persist_target_if_due(self, target: CoverageTarget, *, force: bool = False, reason: str = "") -> bool:
        if not self.persist:
            return False
        now = time.time()
        last_at = float(self._last_persisted_at_by_market.get(target.market_id) or 0)
        if not force and now - last_at < target.sample_interval_seconds:
            return False
        payload = self.manager.get_cached_market_snapshot(
            market_id=target.market_id,
            yes_token_id=target.yes_token_id,
            no_token_id=target.no_token_id,
            market_title=target.market_title,
        )
        payload["coverage"] = {
            "topic": target.topic,
            "tier": target.tier,
            "sampleIntervalSeconds": target.sample_interval_seconds,
            "reason": reason,
        }
        payload["source"] = "local-orderbook"
        lob_service.persist_runtime_lob_payload(self.ctx, payload, target.yes_token_id, target.no_token_id)
        self._last_persisted_at_by_market[target.market_id] = now
        return True


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def acquire(self) -> bool:
        if fcntl is None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            self.fd = fd
            return True
        except BlockingIOError:
            os.close(fd)
            return False

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def start_background_worker(ctx: dict[str, Any], *, lock_dir: str | Path | None = None) -> threading.Thread | None:
    if str(os.environ.get("POLYDATA_LOB_WEBSOCKET_ENABLED", "0")).strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    logger = _Logger()
    ws_url = os.environ.get("POLYDATA_CLOB_WS_URL") or POLYMARKET_CLOB_WS_URL
    if not str(ws_url or "").strip():
        logger.warning("websocket disabled: POLYDATA_CLOB_WS_URL is empty")
        return None
    base_dir = Path(lock_dir or os.environ.get("POLYDATA_RUNTIME_LOCK_DIR") or "/tmp/polydata")
    lock = _FileLock(base_dir / DEFAULT_LOCK_NAME)
    if not lock.acquire():
        logger.info("websocket disabled: another process owns %s", lock.path)
        return None

    def _run() -> None:
        try:
            watcher = LocalOrderBookWebsocketWatcher(
                ctx=ctx,
                ws_url=str(ws_url),
                limit=int(os.environ.get("POLYDATA_LOB_COVERAGE_LIMIT", DEFAULT_COVERAGE_LIMIT) or DEFAULT_COVERAGE_LIMIT),
                topics=os.environ.get("POLYDATA_LOB_COVERAGE_TOPICS", DEFAULT_COVERAGE_TOPICS),
                coverage_refresh_seconds=int(os.environ.get("POLYDATA_LOB_COVERAGE_REFRESH_SECONDS", DEFAULT_COVERAGE_REFRESH_SECONDS) or DEFAULT_COVERAGE_REFRESH_SECONDS),
                bootstrap_market_limit=int(os.environ.get("POLYDATA_LOB_BOOTSTRAP_MARKET_LIMIT", DEFAULT_BOOTSTRAP_MARKET_LIMIT) or DEFAULT_BOOTSTRAP_MARKET_LIMIT),
                persist=str(os.environ.get("POLYDATA_LOB_WS_PERSIST_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"},
                logger=logger,
            )
            asyncio.run(watcher.run_forever())
        finally:
            lock.close()

    thread = threading.Thread(target=_run, name="local-orderbook-websocket", daemon=True)
    thread.start()
    logger.info("websocket background worker started")
    return thread


def build_default_context() -> dict[str, Any]:
    from api_server import build_service_context

    return build_service_context()


def _iter_json_events(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item


def _chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), max(1, int(size))):
        yield values[index : index + size]


def _int_or_none(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply Polymarket CLOB websocket events to the LocalOrderBook registry")
    parser.add_argument("--ws-url", default=os.environ.get("POLYDATA_CLOB_WS_URL") or POLYMARKET_CLOB_WS_URL)
    parser.add_argument("--limit", type=int, default=int(os.environ.get("POLYDATA_LOB_COVERAGE_LIMIT", DEFAULT_COVERAGE_LIMIT) or DEFAULT_COVERAGE_LIMIT))
    parser.add_argument("--topics", default=os.environ.get("POLYDATA_LOB_COVERAGE_TOPICS", DEFAULT_COVERAGE_TOPICS))
    parser.add_argument("--coverage-refresh-seconds", type=int, default=int(os.environ.get("POLYDATA_LOB_COVERAGE_REFRESH_SECONDS", DEFAULT_COVERAGE_REFRESH_SECONDS) or DEFAULT_COVERAGE_REFRESH_SECONDS))
    parser.add_argument("--bootstrap-limit", type=int, default=int(os.environ.get("POLYDATA_LOB_BOOTSTRAP_MARKET_LIMIT", DEFAULT_BOOTSTRAP_MARKET_LIMIT) or DEFAULT_BOOTSTRAP_MARKET_LIMIT))
    parser.add_argument("--run-seconds", type=int, default=0)
    parser.add_argument("--bootstrap-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Apply state in memory but skip database persistence")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    watcher = LocalOrderBookWebsocketWatcher(
        ctx=build_default_context(),
        ws_url=args.ws_url,
        limit=args.limit,
        topics=args.topics,
        coverage_refresh_seconds=args.coverage_refresh_seconds,
        bootstrap_market_limit=args.bootstrap_limit,
        persist=not args.dry_run,
    )
    targets = watcher.refresh_targets()
    watcher.bootstrap_targets(targets[: args.bootstrap_limit] if args.bootstrap_limit else [], force_refresh=True)
    if args.bootstrap_only:
        return 0
    asyncio.run(watcher.run_connection(run_seconds=args.run_seconds if args.run_seconds > 0 else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
