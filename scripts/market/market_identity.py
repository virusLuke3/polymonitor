#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers for keeping local, Gamma, CLOB, and token market identities separate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class MarketIdentity:
    local_market_id: int
    gamma_market_id: Optional[str]
    slug: Optional[str]
    condition_id: Optional[str]
    question_id: Optional[str]
    yes_token_id: Optional[str]
    no_token_id: Optional[str]

    @classmethod
    def from_row(cls, row: Any) -> "MarketIdentity":
        data = _row_to_dict(row)
        return cls(
            local_market_id=int(data.get("id") or data.get("local_market_id") or 0),
            gamma_market_id=_clean_text(data.get("gamma_market_id")),
            slug=_clean_text(data.get("slug")),
            condition_id=_clean_text(data.get("condition_id")),
            question_id=_clean_text(data.get("question_id")),
            yes_token_id=_clean_text(data.get("yes_token_id")),
            no_token_id=_clean_text(data.get("no_token_id")),
        )

    def as_api_dict(self) -> Dict[str, Any]:
        return {
            "localMarketId": self.local_market_id,
            "gammaMarketId": self.gamma_market_id,
            "slug": self.slug,
            "conditionId": self.condition_id,
            "questionId": self.question_id,
            "yesTokenId": self.yes_token_id,
            "noTokenId": self.no_token_id,
        }


def _clean_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "as_dict"):
        return row.as_dict()
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError("row must be a mapping-like DB row")


def oracle_event_lookup_terms(identity: MarketIdentity) -> List[tuple[str, Any]]:
    terms: List[tuple[str, Any]] = [("market_id", identity.local_market_id)]
    if identity.gamma_market_id:
        terms.append(("external_market_id", identity.gamma_market_id))
    if identity.condition_id:
        terms.append(("condition_id", identity.condition_id))
    if identity.question_id:
        terms.append(("question_id", identity.question_id))
    return terms
