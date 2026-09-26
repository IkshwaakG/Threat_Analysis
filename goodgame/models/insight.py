"""Analysis output models suitable for API and visualization layers."""

from dataclasses import dataclass, field
from typing import Any

from goodgame.models.event import Event
from goodgame.models.match import Match


@dataclass(frozen=True)
class Insight:
    id: str
    kind: str
    title: str
    impact: str
    summary: str
    start_minute: int | None = None
    end_minute: int | None = None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchAnalysis:
    match: Match
    events: tuple[Event, ...]
    insights: tuple[Insight, ...]
    lineups: dict[str, Any] = field(default_factory=dict)
    shots: tuple[dict[str, Any], ...] = ()