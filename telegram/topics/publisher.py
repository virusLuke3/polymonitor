from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List

from .api_client import PolyDataApiClient, resolve_polydata_api_base
from .catalog import CATALOG_VERSION, HISTORICAL_GENERIC_PANEL_IDS, SERVER_RUNTIME_PANEL_IDS
from .client import TelegramClient
from .config import TelegramSettings, load_settings
from .formatters import format_all_snapshots_with_stats, format_related_news
from .models import MessageCandidate
from .state import PublishState, state_lock


PANEL_ENDPOINTS = {
    "latest-content": ("/content/latest", {"limit": 8}),
    "alpha-signal": ("/runtime/signals/alpha", {"limit": 8}),
    "new-market-signals": ("/runtime/markets/new-signals", {"limit": 12}),
    "polymarket-macro-map": ("/runtime/macro/polymarket-map", {"limit": 12}),
    "cpi-release-command-center": ("/runtime/macro/cpi-release-command-center", {"limit": 12}),
    "nba-scoreboard": ("/runtime/sports/nba", {"limit": 10}),
    "nba-intel": ("/runtime/sports/nba-intel", {"limit": 12}),
    "espn-matchup-predictor": ("/runtime/sports/nba-matchup-predictor", {"limit": 8}),
    "global-weather-map": ("/runtime/weather/global-map", {"limit": 34}),
    "weather-news": ("/runtime/weather/news", {"limit": 24}),
    "geo-sanctions-shock": ("/runtime/panels/geo-sanctions-shock", {"limit": 12}),
    "policy-progress": ("/runtime/panels/policy-progress", {"limit": 12}),
}
INTEL_PANELS = ("geo-sanctions-shock", "policy-progress")
FETCH_MAX_WORKERS = 4
FETCH_TIMEOUT_SECONDS = 10
HISTORICAL_PANELS_PER_CYCLE = 6
HISTORICAL_PANELS = tuple(
    panel_id for panel_id in HISTORICAL_GENERIC_PANEL_IDS
    if panel_id not in PANEL_ENDPOINTS and panel_id not in {
        # Existing seed workers already publish these snapshots.
        "global-transport-shipping", "cpi-components-pressure-registry", "goods-tariff-supply-watch",
        "labor-services-inflation-monitor", "fed-reaction-growth-risk-board",
    }
)

TARGET_PANELS = {
    "all": tuple(PANEL_ENDPOINTS),
    "news": ("latest-content",),
    "intel": INTEL_PANELS,
    "alpha": ("alpha-signal", "new-market-signals"),
    "macro": ("polymarket-macro-map", "cpi-release-command-center"),
    "nba": ("nba-scoreboard", "nba-intel", "espn-matchup-predictor"),
    "weather": ("global-weather-map", "weather-news"),
    "all-panels": (*SERVER_RUNTIME_PANEL_IDS, "latest-content"),
}


@dataclass
class PublishResult:
    fetched: int = 0
    candidates: int = 0
    sent: int = 0
    previewed: int = 0
    primed: int = 0
    skipped_seen: int = 0
    skipped_unconfigured: int = 0
    failed_sends: int = 0
    fetch_failed: int = 0
    dry_run: bool = False
    api_base: str = ""
    api_healthy: bool = False
    format_specialized: int = 0
    format_generic: int = 0
    format_empty: int = 0
    format_aggregate: int = 0
    format_market_scoped: int = 0
    format_browser_only: int = 0
    format_non_pushable: int = 0
    format_unsupported: int = 0
    format_errors: int = 0
    catalog_primed: bool = False
    last_message_id_by_topic: dict[str, int] = field(default_factory=dict)
    historical_fetched: list[str] = field(default_factory=list)
    historical_unready: list[str] = field(default_factory=list)
    related_markets_checked: int = 0


def _write_heartbeat(*, phase: str, result: PublishResult | None = None, error: str = "") -> None:
    raw_path = str(os.environ.get("POLYDATA_TELEGRAM_HEARTBEAT_PATH") or "").strip()
    if not raw_path:
        return
    path = Path(raw_path).expanduser()
    payload = {
        "timestamp": int(time.time()),
        "phase": phase,
        "error": str(error or "")[:500],
        "result": result.__dict__ if result is not None else None,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        print(f"[telegram-publisher] WARN heartbeat write failed path={path} error={exc}", file=sys.stderr)


def fetch_snapshots(
    api: PolyDataApiClient, *, target: str, historical_panels: tuple[str, ...] = (),
) -> Dict[str, Dict]:
    panel_ids = (*TARGET_PANELS.get(target, TARGET_PANELS["all"]), *historical_panels)
    timeout = min(FETCH_TIMEOUT_SECONDS, api.timeout_seconds)

    def fetch(panel_id: str) -> Dict | None:
        panel_api = api.isolated(timeout_seconds=timeout)
        try:
            with panel_api.session:
                if panel_id in PANEL_ENDPOINTS and (
                    target != "all-panels" or panel_id not in SERVER_RUNTIME_PANEL_IDS
                ):
                    path, params = PANEL_ENDPOINTS[panel_id]
                    return panel_api.get_json(path, params=params)
                envelope = panel_api.get_json(
                    "/v1/runtime/panels",
                    params={"ids": panel_id, "limit": 12},
                )
            data = envelope.get("data") or {}
            payload = (data.get("panels") or {}).get(panel_id)
            if envelope.get("errors") or not isinstance(payload, dict):
                print(
                    f"[telegram-publisher] WARN runtime panel response panel={panel_id} "
                    f"returned={isinstance(payload, dict)}",
                    file=sys.stderr,
                )
            return payload if isinstance(payload, dict) else None
        except Exception as exc:
            print(
                f"[telegram-publisher] WARN fetch failed panel={panel_id} error_class={exc.__class__.__name__}",
                file=sys.stderr,
            )
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_MAX_WORKERS) as executor:
        return {
            panel_id: payload
            for panel_id, payload in zip(panel_ids, executor.map(fetch, panel_ids))
            if payload is not None
        }


def _historical_snapshot_ready(panel_id: str, payload: Dict) -> bool:
    if panel_id == "natural-hazards":
        return bool(payload.get("events"))
    if payload.get("stale") or payload.get("cacheMode") in {"stale", "stale-seed", "warming"}:
        return False
    return payload.get("status") in {"ok", "ready", "partial", "degraded"} and bool(
        payload.get("items") or payload.get("commodities") or payload.get("quarterly")
    )


def _fetch_related_candidates(api: PolyDataApiClient, macro_snapshot: Dict) -> tuple[list[MessageCandidate], int]:
    # Reuse the macro monitor's leading local market per event and the public content matcher.
    market_ids = {}
    for event in macro_snapshot.get("items") or []:
        outcomes = event.get("topOutcomes") or []
        if outcomes and (market_id := outcomes[0].get("marketId")):
            market_ids.setdefault(market_id, None)

    candidates = []
    checked = 0
    for market_id in list(market_ids)[:6]:
        try:
            payload = api.get_json(f"/content/market/{market_id}", params={"limit": 8}, timeout_seconds=3)
        except Exception as exc:
            print(f"[telegram-publisher] WARN related-news fetch failed error_class={type(exc).__name__}", file=sys.stderr)
            continue
        checked += 1
        if not payload.get("stale") and payload.get("marketId") == market_id:
            candidates.extend(format_related_news(payload))
    return candidates, checked


def _candidate_targets(candidate: MessageCandidate, settings: TelegramSettings) -> Iterable[str]:
    for target in candidate.targets():
        config = settings.topic_config(target)
        if config.enabled:
            yield target


def _all_panels_fetch_complete(snapshots: Dict[str, Dict]) -> bool:
    expected = set(TARGET_PANELS["all-panels"])
    return expected.issubset(snapshots) and len(snapshots) == len(expected)


def publish_candidates(
    candidates: List[MessageCandidate],
    *,
    settings: TelegramSettings,
    state: PublishState,
    telegram: TelegramClient,
    dry_run: bool = False,
    prime: bool = False,
) -> PublishResult:
    result = PublishResult(candidates=len(candidates), dry_run=dry_run)
    for candidate in candidates:
        targets = list(candidate.targets()) if prime or dry_run else list(_candidate_targets(candidate, settings))
        if not targets:
            result.skipped_unconfigured += 1
            continue
        for target in targets:
            if state.seen(target, candidate.dedupe_key):
                result.skipped_seen += 1
                continue
            config = settings.topic_config(target)
            if dry_run:
                print(json.dumps({"target": target, "dedupeKey": candidate.dedupe_key, "text": candidate.text}, ensure_ascii=False))
                result.previewed += 1
                result.sent += 1
                continue
            if prime:
                state.mark(target, candidate.dedupe_key)
                result.primed += 1
                continue
            else:
                try:
                    receipts = telegram.send_message(
                        chat_id=config.chat_id,
                        text=candidate.text,
                        message_thread_id=config.message_thread_id,
                        disable_web_page_preview=not candidate.link_preview,
                        disable_notification=settings.disable_notification,
                        reply_markup=candidate.reply_markup,
                    )
                except Exception as exc:
                    result.failed_sends += 1
                    print(
                        f"[telegram-publisher] WARN send failed target={target} dedupe={candidate.dedupe_key} error_class={exc.__class__.__name__}",
                        file=sys.stderr,
                    )
                    continue
                receipt = receipts[-1].get("result") if receipts else None
                if receipt and receipt.get("message_id"):
                    result.last_message_id_by_topic[target] = receipt["message_id"]
                state.mark(
                    target, candidate.dedupe_key, panel_id=candidate.metadata.get("panel", ""),
                    receipt=receipt if receipt and receipt.get("message_id") else None,
                )
                result.sent += 1
    if not dry_run:
        state.save()
    return result


def run_once(
    *,
    settings: TelegramSettings,
    target: str,
    dry_run: bool = False,
    prime: bool = False,
    api_base_override: str = "",
    historical_panels: tuple[str, ...] = (),
    include_related: bool = False,
) -> PublishResult:
    api_candidates = (api_base_override.rstrip("/"),) if api_base_override else settings.polydata_api_candidates
    resolution = resolve_polydata_api_base(api_candidates, timeout_seconds=min(5, settings.request_timeout_seconds))
    if not resolution.healthy:
        checked = ", ".join(resolution.checked) or "(none)"
        print(f"[telegram-publisher] WARN no healthy polyData API found; using {resolution.base_url or '(empty)'} after checking {checked}", file=sys.stderr)
    api = PolyDataApiClient(base_url=resolution.base_url or settings.polydata_api_base, timeout_seconds=settings.request_timeout_seconds)
    telegram = TelegramClient(
        bot_token=settings.bot_token,
        api_base=settings.telegram_api_base,
        timeout_seconds=settings.request_timeout_seconds,
    )
    snapshots = fetch_snapshots(api, target=target, historical_panels=historical_panels)
    historical_unready = [
        panel_id for panel_id in historical_panels
        if panel_id in snapshots and not _historical_snapshot_ready(panel_id, snapshots[panel_id])
    ]
    publishable_snapshots = {
        panel_id: payload
        for panel_id, payload in snapshots.items()
        if panel_id not in historical_unready and (
            target == "all-panels"
            or panel_id not in INTEL_PANELS
            or (payload.get("status") == "ok" and payload.get("items"))
        )
    }
    candidates, format_stats = format_all_snapshots_with_stats(publishable_snapshots)
    related_checked = 0
    if include_related and (macro := snapshots.get("polymarket-macro-map")):
        related, related_checked = _fetch_related_candidates(api, macro)
        candidates.extend(related)
    with state_lock(settings.state_path):
        state = PublishState(settings.state_path)
        auto_prime = target == "all-panels" and not dry_run and not state.catalog_primed(CATALOG_VERSION)
        effective_prime = bool(prime or auto_prime)
        result = publish_candidates(
            candidates,
            settings=settings,
            state=state,
            telegram=telegram,
            dry_run=dry_run,
            prime=effective_prime,
        )
        all_panels_complete = _all_panels_fetch_complete(snapshots)
        if target == "all-panels" and effective_prime and all_panels_complete:
            state.mark_catalog_primed(CATALOG_VERSION)
            state.save()
            result.catalog_primed = True
    result.fetched = len(snapshots)
    result.fetch_failed = len(TARGET_PANELS.get(target, TARGET_PANELS["all"])) + len(historical_panels) - len(snapshots)
    result.api_base = api.base_url
    result.api_healthy = resolution.healthy
    result.format_specialized = format_stats["specialized"]
    result.format_generic = format_stats["generic"]
    result.format_empty = format_stats["empty"]
    result.format_aggregate = format_stats["aggregate"]
    result.format_market_scoped = format_stats["market_scoped"]
    result.format_browser_only = format_stats["browser_only"]
    result.format_non_pushable = format_stats["non_pushable"]
    result.format_unsupported = format_stats["unsupported"]
    result.format_errors = format_stats["format_errors"]
    result.historical_fetched = [panel_id for panel_id in historical_panels if panel_id in snapshots]
    result.historical_unready = historical_unready
    result.related_markets_checked = related_checked
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish polyData runtime panel snapshots to Telegram channels")
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--once", action="store_true", help="Run one publish cycle and exit")
    parser.add_argument("--target", choices=sorted(TARGET_PANELS), default="all")
    parser.add_argument("--interval", type=int, default=None, help="Watch interval in seconds")
    parser.add_argument("--api-base", default="", help="Override polyData API base URL for this run")
    parser.add_argument("--dry-run", action="store_true", help="Print outgoing messages without calling Telegram")
    parser.add_argument(
        "--prime",
        action="store_true",
        help="Mark current candidates as seen without sending them; all-panels also primes automatically on its first live run",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    settings = load_settings()
    dry_run = bool(args.dry_run or settings.dry_run)
    if not dry_run and not args.prime and not settings.bot_token:
        print("POLYDATA_TELEGRAM_BOT_TOKEN is required. Use --dry-run or --prime to run without sending.", file=sys.stderr)
        return 2

    interval = max(15, int(args.interval or settings.watch_interval_seconds))
    historical_offset = 0
    _write_heartbeat(phase="starting")
    while True:
        _write_heartbeat(phase="cycle-start")
        try:
            scheduled = args.watch and args.target == "all"
            historical = HISTORICAL_PANELS[historical_offset:historical_offset + HISTORICAL_PANELS_PER_CYCLE] if scheduled else ()
            result = run_once(
                settings=settings, target=args.target, dry_run=dry_run, prime=bool(args.prime),
                api_base_override=str(args.api_base or ""), historical_panels=historical,
                include_related=scheduled and historical_offset == 0,
            )
            if historical:
                historical_offset = historical_offset + len(historical)
                if historical_offset >= len(HISTORICAL_PANELS):
                    historical_offset = 0
            print(json.dumps(result.__dict__, ensure_ascii=True), file=sys.stderr)
            _write_heartbeat(phase="cycle-complete", result=result)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"[telegram-publisher] ERROR {exc}", file=sys.stderr)
            _write_heartbeat(phase="cycle-error", error=str(exc))
            if not args.watch:
                return 1
        if not args.watch:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
