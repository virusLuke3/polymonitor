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

from requests.exceptions import ConnectTimeout

from .api_client import PolyDataApiClient, resolve_polydata_api_base
from .catalog import DELIVERY_CATALOG, SERVER_RUNTIME_PANEL_IDS
from .client import SAFE_TEXT_LENGTH, TelegramClient, TelegramSendRejected
from .config import TelegramSettings, load_settings
from .formatters import format_all_snapshots_with_stats, format_related_news
from .generic_formatter import SUMMARY_KEY_PREFIX
from .models import MessageCandidate, source_clock
from .source_alerts import COMMODITIES, ESPORTS, ORACLE, ORDER_FLOW, SOURCE_LIMITS, STATE_SUFFIX, plan_source_alerts
from .state import PublishState, state_lock


PANEL_ENDPOINTS = {
    "latest-content": ("/content/latest", {"limit": 36}),
    "alpha-signal": ("/runtime/signals/alpha", {"limit": 8}),
    "new-market-signals": ("/runtime/markets/new-signals", {"limit": 12}),
    "whale-tracker": ("/runtime/panels/whale-tracker", {"limit": 24}),
    "suspicious-flow": ("/runtime/panels/suspicious-flow", {"limit": 24}),
    "polymarket-macro-map": ("/runtime/macro/polymarket-map", {"limit": 12}),
    "cpi-release-command-center": ("/runtime/macro/cpi-release-command-center", {"limit": 12}),
    "nba-scoreboard": ("/runtime/sports/nba", {"limit": 10}),
    "nba-intel": ("/runtime/sports/nba-intel", {"limit": 12}),
    "espn-matchup-predictor": ("/runtime/sports/nba-matchup-predictor", {"limit": 8}),
    ESPORTS: ("/runtime/esports/grid-intel", {"limit": 36}),
    ORDER_FLOW: ("/runtime/crypto/order-flow", {}),
    ORACLE: ("/runtime/crypto/oracle-reference", {}),
    COMMODITIES: ("/runtime/markets/commodities", {"limit": 36}),
    "global-weather-map": ("/runtime/weather/global-map", {"limit": 34}),
    "weather-news": ("/runtime/weather/news", {"limit": 24}),
    "geo-sanctions-shock": ("/runtime/panels/geo-sanctions-shock", {"limit": 12}),
    "policy-progress": ("/runtime/panels/policy-progress", {"limit": 12}),
}
FETCH_MAX_WORKERS = 4
FETCH_TIMEOUT_SECONDS = 10
MAX_MESSAGE_AGE_SECONDS = 20 * 60
ROTATING_PANELS_PER_CYCLE = 12
LISTING_PANEL = "crypto-listing-watch"
ROTATING_PANELS = tuple(
    panel_id for panel_id in SERVER_RUNTIME_PANEL_IDS
    if panel_id not in PANEL_ENDPOINTS and DELIVERY_CATALOG[panel_id].pushable
)

TARGET_PANELS = {
    "all": tuple(PANEL_ENDPOINTS),
    "news": ("latest-content",),
    "intel": ("geo-sanctions-shock", "policy-progress", ESPORTS, ORDER_FLOW, ORACLE),
    "alpha": ("alpha-signal", "new-market-signals", "whale-tracker", "suspicious-flow"),
    "macro": ("polymarket-macro-map", "cpi-release-command-center", COMMODITIES),
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
    uncertain_sends: int = 0
    retryable_keys: list[str] = field(default_factory=list)
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
    message_ids_by_topic: dict[str, list[int]] = field(default_factory=dict)
    historical_fetched: list[str] = field(default_factory=list)
    historical_unready: list[str] = field(default_factory=list)
    related_markets_checked: int = 0
    baselined_sources: list[str] = field(default_factory=list)
    empty_sources: list[str] = field(default_factory=list)
    selected_by_topic: dict[str, list[str]] = field(default_factory=dict)


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
                    target != "all-panels" or panel_id in SOURCE_LIMITS or panel_id not in SERVER_RUNTIME_PANEL_IDS
                ):
                    path, params = PANEL_ENDPOINTS[panel_id]
                    return panel_api.get_json(path, params=params)
                envelope = panel_api.get_json(
                    "/v1/runtime/panels",
                    params={"ids": panel_id, "limit": 36},
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


def _snapshot_ready(payload: Dict) -> bool:
    blocked = {"stale", "retained", "warming", "empty", "unavailable", "error", "failed", "disabled", "invalid"}
    return not (
        payload.get("stale") or str(payload.get("status")).lower() in blocked
        or str(payload.get("cacheMode")).lower().startswith(("stale", "retained", "warming"))
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
            payload = api.get_json(f"/content/market/{market_id}", params={"limit": 24}, timeout_seconds=3)
        except Exception as exc:
            print(f"[telegram-publisher] WARN related-news fetch failed error_class={type(exc).__name__}", file=sys.stderr)
            continue
        checked += 1
        if _snapshot_ready(payload) and payload.get("marketId") == market_id:
            for article in payload.get("items") or []:
                if isinstance(article, dict) and source_clock(article, "publishedAt", "published_at"):
                    candidates.extend(format_related_news({**payload, "items": [article]}))
    return candidates, checked


def _candidate_targets(candidate: MessageCandidate, settings: TelegramSettings) -> Iterable[str]:
    for target in candidate.targets():
        config = settings.topic_config(target)
        if config.enabled:
            yield target


def _listing_changes(snapshot: Dict, prior: Dict, now: float) -> tuple[dict | None, list[MessageCandidate]]:
    stamp = source_clock(snapshot, "generatedAt")
    modes = snapshot.get("productModes")
    previous_stamp = prior.get("at", 0)
    if (
        snapshot.get("status") != "ok" or not isinstance(modes, dict) or not modes
        or stamp is None or stamp <= previous_stamp or not 0 <= now - stamp <= MAX_MESSAGE_AGE_SECONDS
    ):
        return None, []
    observation = {"at": stamp, "productModes": modes}
    previous_modes = prior.get("productModes")
    if not previous_modes or stamp - previous_stamp > MAX_MESSAGE_AGE_SECONDS:
        return observation, []
    candidates = []
    for pair, mode in sorted(modes.items()):
        before = previous_modes.get(pair)
        if mode == "unknown" or mode == before:
            continue
        change = f"{before} → {mode}" if before else f"Newly observed product | {mode}"
        candidates.append(MessageCandidate(
            topic=DELIVERY_CATALOG[LISTING_PANEL].topic,
            dedupe_key=f"listing:{pair}:{previous_stamp}:{mode}",
            text=f"📡 Coinbase Exchange product update\n{pair} | {change}\n#CryptoListing",
            metadata={"panel": LISTING_PANEL, "formatter": "coinbase-product-change"},
        ))
    return observation, candidates


def _new_candidates(
    candidates: list[MessageCandidate], snapshots: Dict[str, Dict], state: PublishState, *,
    now: float, live_since: float, prime: bool, dry_run: bool,
) -> tuple[list[MessageCandidate], dict, list[str]]:
    snapshots_by_source: dict[str, list[MessageCandidate]] = {}
    heads = state.payload["sourceHeads"]
    chosen: dict[tuple[str, str], tuple[float, MessageCandidate]] = {}
    baselined = set()
    if prime:
        baselined.update(snapshots)
        baselined.update(candidate.metadata["panel"] for candidate in candidates)
    updated = {f"{panel}:event": {"after": now} for panel in baselined}

    def select(candidate: MessageCandidate, stamp: float) -> None:
        key = (candidate.topic, candidate.dedupe_key)
        if not live_since < stamp <= now or now - stamp > MAX_MESSAGE_AGE_SECONDS or state.seen(*key):
            return
        prior = chosen.get(key)
        if prior is None or stamp > prior[0]:
            chosen[key] = (stamp, candidate)

    for candidate in candidates:
        panel = candidate.metadata["panel"]
        stamp = candidate.observed_at
        if stamp is None:
            snapshots_by_source.setdefault(panel, []).append(candidate)
        elif not prime and stamp > heads.get(f"{panel}:event", {}).get("after", 0):
            select(candidate, stamp)
    for panel, entries in snapshots_by_source.items():
        stamp = source_clock(snapshots.get(panel, {}), "collectedAt", "generatedAt", "updatedAt")
        if stamp is None or stamp > now:
            continue
        prior = heads.get(panel)
        keys = sorted({candidate.dedupe_key for candidate in entries})
        if prime or (prior is None and not dry_run):
            updated[panel] = {"at": stamp, "keys": keys}
            baselined.add(panel)
            continue
        prior_at = (prior or {}).get("at", 0)
        if stamp <= prior_at:
            continue
        prior_keys = set((prior or {}).get("keys", []))
        # Adopt the visible-body signature without re-announcing existing snapshots.
        summary_keys = {key for key in keys if key.startswith(SUMMARY_KEY_PREFIX)}
        if summary_keys and not any(key.startswith(SUMMARY_KEY_PREFIX) for key in prior_keys):
            prior_keys.update(summary_keys)
            baselined.add(panel)
        updated[panel] = {"at": stamp, "keys": keys}
        for candidate in entries:
            if candidate.dedupe_key not in prior_keys:
                select(candidate, stamp)
    ordered = sorted(chosen.values(), key=lambda entry: entry[0])
    return [candidate for _, candidate in ordered], updated, sorted(baselined)


def publish_candidates(
    candidates: List[MessageCandidate],
    *,
    settings: TelegramSettings,
    state: PublishState,
    telegram: TelegramClient,
    dry_run: bool = False,
    prime: bool = False,
    primary_only: bool = False,
) -> PublishResult:
    result = PublishResult(candidates=len(candidates), dry_run=dry_run)
    for candidate in candidates:
        panel = candidate.metadata.get("panel", "")
        limits = SOURCE_LIMITS.get(panel)
        if limits and (candidate.observed_at is None or time.time() - candidate.observed_at > limits[0]):
            continue
        if primary_only:
            targets = [candidate.topic] if settings.topic_config(candidate.topic).enabled or dry_run else []
        else:
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
                state.mark(target, candidate.dedupe_key, panel_id=panel, pending=True)
                state.save()
                try:
                    receipts = telegram.send_message(
                        chat_id=config.chat_id,
                        text=candidate.text[:SAFE_TEXT_LENGTH] if primary_only else candidate.text,
                        message_thread_id=config.message_thread_id,
                        disable_web_page_preview=not candidate.link_preview,
                        disable_notification=settings.disable_notification,
                        reply_markup=candidate.reply_markup,
                        **({"expires_at": candidate.observed_at + limits[0]} if limits else {}),
                    )
                except Exception as exc:
                    result.failed_sends += 1
                    if isinstance(exc, (ConnectTimeout, TelegramSendRejected)):
                        state.forget(target, candidate.dedupe_key)
                        state.save()
                        result.retryable_keys.append(candidate.dedupe_key)
                    else:
                        result.uncertain_sends += 1
                    print(
                        f"[telegram-publisher] WARN send failed target={target} dedupe={candidate.dedupe_key} error_class={exc.__class__.__name__}",
                        file=sys.stderr,
                    )
                    continue
                receipt = receipts[-1].get("result") if receipts else None
                if primary_only and not (receipt and receipt.get("message_id")):
                    result.failed_sends += 1
                    result.uncertain_sends += 1
                    continue
                if receipt and receipt.get("message_id"):
                    result.last_message_id_by_topic[target] = receipt["message_id"]
                    result.message_ids_by_topic.setdefault(target, []).append(receipt["message_id"])
                state.mark(
                    target, candidate.dedupe_key, panel_id=panel,
                    receipt=receipt if receipt and receipt.get("message_id") else None,
                    source_at=candidate.observed_at if limits else None,
                )
                state.save()
                result.sent += 1
    if prime and not dry_run:
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
    started_at = time.time()
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
        panel_id for panel_id, payload in snapshots.items()
        if not _snapshot_ready(payload)
        and not (panel_id == "crypto-funding-watch" and (payload.get("settlementWatch") or {}).get("batches"))
    ]
    publishable_snapshots = {
        panel_id: payload
        for panel_id, payload in snapshots.items()
        if panel_id not in historical_unready
    }
    ordinary_snapshots = {
        panel_id: payload for panel_id, payload in publishable_snapshots.items() if panel_id not in SOURCE_LIMITS
    }
    candidates, format_stats = format_all_snapshots_with_stats(ordinary_snapshots, live=True)
    related_checked = 0
    if include_related and (macro := publishable_snapshots.get("polymarket-macro-map")):
        related, related_checked = _fetch_related_candidates(api, macro)
        candidates.extend(related)
    with state_lock(settings.state_path):
        state = PublishState(settings.state_path)
        now = time.time()
        window = state.payload["deliveryWindow"]
        live_since = window.get("startedAt", started_at)
        if not dry_run and not prime:
            window.setdefault("startedAt", live_since)
        listing_prior = state.payload["sourceHeads"].get(LISTING_PANEL, {})
        listing_observation, listing_candidates = _listing_changes(
            publishable_snapshots.get(LISTING_PANEL, {}), {} if prime else listing_prior, now,
        )
        candidates.extend(listing_candidates)
        chosen, observations, baselined = _new_candidates(
            candidates, ordinary_snapshots, state, now=now, live_since=live_since, prime=prime, dry_run=dry_run,
        )
        source_candidates, source_observations, source_baselined = plan_source_alerts(
            publishable_snapshots, state.payload["sourceHeads"], now=now, prime=prime,
        )
        baselined.extend(source_baselined)
        observations.update(source_observations)
        chosen = source_candidates + chosen
        if listing_observation is not None:
            observations.setdefault(LISTING_PANEL, {}).update(listing_observation)
            if prime or not listing_prior.get("productModes"):
                baselined.append(LISTING_PANEL)
        result = publish_candidates(
            chosen,
            settings=settings,
            state=state,
            telegram=telegram,
            dry_run=dry_run,
            primary_only=True,
        )
        if not dry_run:
            retryable = set(result.retryable_keys)
            for candidate in chosen:
                if candidate.dedupe_key not in retryable:
                    continue
                panel = candidate.metadata["panel"]
                if panel in SOURCE_LIMITS:
                    observations.pop(panel + STATE_SUFFIX, None)
                elif candidate.observed_at is None:
                    observations.pop(panel, None)
            state.payload["sourceHeads"].update(observations)
            state.save()
    result.baselined_sources = baselined
    candidate_panels = {candidate.metadata["panel"] for candidate in candidates + source_candidates}
    result.empty_sources = sorted(
        panel for panel in publishable_snapshots if DELIVERY_CATALOG[panel].pushable and panel not in candidate_panels
    )
    for candidate in chosen:
        result.selected_by_topic.setdefault(candidate.topic, []).append(candidate.metadata["panel"])
    result.candidates = len(candidates) + len(source_candidates)
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
        help="Record the current source positions without posting them",
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
        started = time.monotonic()
        _write_heartbeat(phase="cycle-start")
        try:
            scheduled = args.watch and args.target == "all"
            historical = ROTATING_PANELS[historical_offset:historical_offset + ROTATING_PANELS_PER_CYCLE] if scheduled else ()
            result = run_once(
                settings=settings, target=args.target, dry_run=dry_run, prime=bool(args.prime),
                api_base_override=str(args.api_base or ""), historical_panels=historical,
                include_related=scheduled and historical_offset == 0,
            )
            if historical:
                historical_offset = historical_offset + len(historical)
                if historical_offset >= len(ROTATING_PANELS):
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
        time.sleep(max(1, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    raise SystemExit(main())
