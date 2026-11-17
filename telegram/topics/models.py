from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Tuple


def source_clock(row: Dict[str, Any], *fields: str) -> float | None:
    for field in fields:
        value = row.get(field)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) or isinstance(value, str) and value.isdigit():
            stamp = float(value)
            if 1_000_000_000 <= stamp < 10_000_000_000:
                return stamp
            if 1_000_000_000_000 <= stamp < 10_000_000_000_000:
                return stamp / 1000
        elif isinstance(value, str) and ("T" in value or " " in value):
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).timestamp()
    return None


@dataclass(frozen=True)
class MessageCandidate:
    topic: str
    dedupe_key: str
    text: str
    priority: str = "normal"
    metadata: Dict[str, Any] = field(default_factory=dict)
    link_preview: bool = False
    reply_markup: Dict[str, Any] | None = None
    observed_at: float | None = None

    def targets(self) -> Tuple[str, ...]:
        extra = ("monitor",) if self.priority == "high" and self.topic != "monitor" else ()
        return (self.topic, *extra)


@dataclass(frozen=True)
class FormatOutcome:
    panel_id: str
    mode: str
    candidates: Tuple[MessageCandidate, ...] = ()
    reason: str = ""

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)
