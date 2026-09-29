#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read and interpret an existing NBA market catalog. Collection belongs to market-data."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


_scripts_root = Path(__file__).resolve().parent.parent
if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))


from NBA.common import (
    DEFAULT_DATA_ROOT,
    MARKET_CATALOG_COLUMNS,
    TOKEN_CATALOG_COLUMNS,
    iso_now,
    load_market_catalog_rows,
    parse_json_list,
    safe_json_dumps,
)

NBA_TAG_SLUG = "nba"
HTTP_TIMEOUT_SECONDS = 30
MATCHUP_PATTERN = re.compile(r"\s(?:vs\.?|at|@)\s", re.IGNORECASE)
MATCHUP_EXTRACT_PATTERN = re.compile(
    r"(?P<team_a>[A-Za-z0-9][A-Za-z0-9.'& -]*?)\s+(?:vs\.?|at|@)\s+(?P<team_b>[A-Za-z0-9][A-Za-z0-9.'& -]*)",
    re.IGNORECASE,
)
PLAYOFF_KEYWORDS = ("playoff", "playoffs")
GENERIC_TAG_SLUGS = {
    "sports",
    "nba",
    "basketball",
    "games",
    "nba-playoffs",
    "2026-nba-playoffs",
    "overunder",
}


def is_head_to_head_event(event: Dict[str, Any]) -> bool:
    return extract_matchup_pair(event) is not None


def _normalize_team_name(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _extract_matchup_pair_from_text(text: str) -> Optional[Tuple[str, str]]:
    text = str(text or "").strip()
    if not text:
        return None
    if text.lower().startswith("will "):
        return None
    match = MATCHUP_EXTRACT_PATTERN.search(text)
    if not match:
        return None
    team_a = _normalize_team_name(match.group("team_a"))
    team_b = _normalize_team_name(match.group("team_b"))
    if not team_a or not team_b or team_a == team_b:
        return None
    return tuple(sorted((team_a, team_b)))


def extract_matchup_pair(event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    title = str(event.get("title") or event.get("name") or "").strip()
    pair = _extract_matchup_pair_from_text(title)
    if pair:
        return pair

    tags = event.get("tags") or []
    team_tags = []
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            slug = str(tag.get("slug") or "").strip().lower()
            if not slug or slug in GENERIC_TAG_SLUGS or any(keyword in slug for keyword in PLAYOFF_KEYWORDS):
                continue
            label = str(tag.get("label") or slug).strip()
            if label:
                team_tags.append(_normalize_team_name(label))
    unique_team_tags = sorted({item for item in team_tags if item})
    if len(unique_team_tags) == 2:
        return tuple(unique_team_tags)

    markets = event.get("markets") or []
    if isinstance(markets, list):
        for market in markets:
            if not isinstance(market, dict):
                continue
            pair = _extract_matchup_pair_from_text(market.get("question") or market.get("title") or "")
            if pair:
                return pair
    return None


def is_explicit_playoff_event(event: Dict[str, Any]) -> bool:
    text_parts = [
        str(event.get("title") or event.get("name") or ""),
        str(event.get("slug") or ""),
        str(event.get("description") or ""),
    ]
    markets = event.get("markets") or []
    if isinstance(markets, list):
        for market in markets[:3]:
            if not isinstance(market, dict):
                continue
            text_parts.append(str(market.get("question") or market.get("title") or ""))
            text_parts.append(str(market.get("description") or ""))
    haystack = " ".join(text_parts).lower()
    if any(keyword in haystack for keyword in PLAYOFF_KEYWORDS):
        return True

    tags = event.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            slug = str(tag.get("slug") or "").strip().lower()
            label = str(tag.get("label") or "").strip().lower()
            if any(keyword in slug for keyword in PLAYOFF_KEYWORDS) or any(keyword in label for keyword in PLAYOFF_KEYWORDS):
                return True
    return False


def filter_playoff_head_to_head_events(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidate_events = [event for event in events if isinstance(event, dict) and is_head_to_head_event(event)]
    explicit_playoff_pairs = {
        pair
        for event in candidate_events
        if is_explicit_playoff_event(event)
        for pair in [extract_matchup_pair(event)]
        if pair
    }

    filtered: List[Dict[str, Any]] = []
    for event in candidate_events:
        if is_explicit_playoff_event(event):
            filtered.append(event)
            continue
        pair = extract_matchup_pair(event)
        if pair and pair in explicit_playoff_pairs:
            filtered.append(event)
    return filtered


def is_head_to_head_market(event: Dict[str, Any], market: Dict[str, Any]) -> bool:
    question = str(market.get("question") or market.get("title") or "").strip()
    slug = str(market.get("slug") or "").strip()
    combined = f"{question} {slug}".lower()
    event_pair = extract_matchup_pair(event)
    market_pair = _extract_matchup_pair_from_text(question) or _extract_matchup_pair_from_text(slug.replace("-", " "))

    if not event_pair:
        return False

    team_a, team_b = event_pair
    mentions_both_teams = team_a in combined and team_b in combined
    pair_matches = market_pair == event_pair if market_pair else mentions_both_teams
    if not pair_matches:
        return False

    if "who will win series" in combined:
        return True

    if "1h" in combined or "2h" in combined or "3q" in combined or "4q" in combined:
        return False
    if "spread" in combined or "o/u" in combined or "total games" in combined:
        return False

    if "moneyline" in combined:
        return True

    # Canonical game winner markets often use the bare matchup title without a suffix.
    return ":" not in question and market_pair == event_pair


def merge_market_catalog_rows(
    previous_rows: Sequence[Dict[str, Any]],
    current_db_rows: Dict[str, Dict[str, Any]],
    active_condition_ids: Sequence[str],
    *,
    seen_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    seen_at = seen_at or iso_now()
    previous_by_condition = {
        str(row.get("condition_id") or "").strip(): dict(row)
        for row in previous_rows
        if str(row.get("condition_id") or "").strip()
    }
    active_set = {str(condition_id).strip() for condition_id in active_condition_ids if str(condition_id).strip()}
    merged: List[Dict[str, Any]] = []
    all_condition_ids = sorted(set(previous_by_condition) | set(current_db_rows))
    for condition_id in all_condition_ids:
        previous = previous_by_condition.get(condition_id, {})
        current = current_db_rows.get(condition_id, {})
        if not previous and not current:
            continue
        current_active = 1 if condition_id in active_set else 0
        discovered_at = str(previous.get("discovered_at") or seen_at)
        last_seen_at = seen_at if current_active else str(previous.get("last_seen_at") or seen_at)
        row = {
            "market_id": int(current.get("id") or previous.get("market_id") or 0),
            "condition_id": condition_id,
            "slug": str(current.get("slug") or previous.get("slug") or ""),
            "title": str(current.get("title") or previous.get("title") or ""),
            "yes_token_id": str(current.get("yes_token_id") or previous.get("yes_token_id") or ""),
            "no_token_id": str(current.get("no_token_id") or previous.get("no_token_id") or ""),
            "clob_token_ids": safe_json_dumps(parse_json_list(current.get("clob_token_ids") or previous.get("clob_token_ids"))),
            "tags": str(current.get("tags") or previous.get("tags") or "[]"),
            "enable_neg_risk": int(current.get("enable_neg_risk") or previous.get("enable_neg_risk") or 0),
            "active": current_active,
            "end_date": str(current.get("end_date") or previous.get("end_date") or ""),
            "discovered_at": discovered_at,
            "last_seen_at": last_seen_at,
        }
        merged.append({column: row.get(column) for column in MARKET_CATALOG_COLUMNS})
    merged.sort(key=lambda item: (-int(item["active"]), str(item["end_date"] or ""), int(item["market_id"] or 0)))
    return merged


def build_token_catalog_rows(market_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    token_rows: List[Dict[str, Any]] = []
    for row in market_rows:
        market_id = int(row.get("market_id") or 0)
        condition_id = str(row.get("condition_id") or "")
        slug = str(row.get("slug") or "")
        title = str(row.get("title") or "")
        yes_token_id = str(row.get("yes_token_id") or "")
        no_token_id = str(row.get("no_token_id") or "")
        token_ids = parse_json_list(row.get("clob_token_ids"))
        if not token_ids:
            token_ids = [token for token in (yes_token_id, no_token_id) if token]
        for index, token_id in enumerate(token_ids):
            outcome = f"OUTCOME_{index}"
            if token_id == yes_token_id:
                outcome = "YES"
            elif token_id == no_token_id:
                outcome = "NO"
            token_rows.append(
                {
                    "market_id": market_id,
                    "condition_id": condition_id,
                    "slug": slug,
                    "title": title,
                    "token_id": token_id,
                    "outcome": outcome,
                    "outcome_index": index,
                    "active": int(row.get("active") or 0),
                    "end_date": str(row.get("end_date") or ""),
                    "discovered_at": str(row.get("discovered_at") or ""),
                    "last_seen_at": str(row.get("last_seen_at") or ""),
                }
            )
    token_rows.sort(key=lambda item: (int(item["market_id"]), int(item["outcome_index"])))
    return [{column: row.get(column) for column in TOKEN_CATALOG_COLUMNS} for row in token_rows]


def _resolve_market_rows_for_print(data_root: Path | str, *, active_only: bool) -> List[Dict[str, Any]]:
    rows = load_market_catalog_rows(data_root)
    if active_only:
        rows = [row for row in rows if int(row.get("active") or 0) == 1]
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NBA-only Polymarket market catalog")
    sub = parser.add_subparsers(dest="command", required=True)


    list_cmd = sub.add_parser("list-nba-markets", help="Print market rows from the NBA catalog")
    list_cmd.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    list_cmd.add_argument("--active-only", action="store_true")
    list_cmd.add_argument("--limit", type=int, default=0)
    return parser


def command_list(args: argparse.Namespace) -> int:
    rows = _resolve_market_rows_for_print(args.data_root, active_only=bool(args.active_only))
    if args.limit and args.limit > 0:
        rows = rows[: int(args.limit)]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "list-nba-markets":
        return command_list(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
