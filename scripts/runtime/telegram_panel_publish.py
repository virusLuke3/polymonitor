"""Best-effort Telegram publishing for freshly cached runtime panel payloads."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict


_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def _enabled() -> bool:
    raw = os.environ.get("POLYDATA_TELEGRAM_PUBLISH_ON_PANEL_CACHE", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def publish_cached_panel_snapshot(panel_id: str, payload: Dict[str, Any]) -> int:
    if not _enabled() or not isinstance(payload, dict):
        return 0
    try:
        from telegram.topics.client import TelegramClient
        from telegram.topics.config import load_settings
        from telegram.topics.formatters import format_panel_snapshot
        from telegram.topics.publisher import publish_candidates
        from telegram.topics.state import PublishState, state_lock
    except Exception as exc:
        print(f"[telegram-panel-publish] WARN imports unavailable panel={panel_id} error={exc}", file=sys.stderr)
        return 0

    try:
        settings = load_settings()
        if not settings.bot_token and not settings.dry_run:
            return 0
        candidates = format_panel_snapshot(panel_id, payload)
        if not candidates:
            return 0
        telegram = TelegramClient(
            bot_token=settings.bot_token,
            api_base=settings.telegram_api_base,
            timeout_seconds=settings.request_timeout_seconds,
        )
        with state_lock(settings.state_path):
            state = PublishState(settings.state_path)
            result = publish_candidates(
                candidates,
                settings=settings,
                state=state,
                telegram=telegram,
                dry_run=settings.dry_run,
            )
        if result.sent or result.skipped_seen:
            print(
                f"[telegram-panel-publish] panel={panel_id} candidates={result.candidates} sent={result.sent} skipped_seen={result.skipped_seen}",
                file=sys.stderr,
            )
        return int(result.sent or 0)
    except Exception as exc:
        print(f"[telegram-panel-publish] WARN publish failed panel={panel_id} error={exc}", file=sys.stderr)
        return 0
