"""Normalized match and team data."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    slug: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Team":
        return cls(
            id=int(payload["id"]),
            name=str(payload.get("name", "Unknown team")),
            slug=payload.get("slug"),
        )


def _score_value(payload: Any) -> int | None:
    if isinstance(payload, Mapping):
        payload = payload.get("current")
        if payload is None:
            payload = payload.get("display")
    try:
        return int(payload) if payload is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Match:
    id: int
    home_team: Team
    away_team: Team
    home_score: int | None
    away_score: int | None
    status: str
    start_timestamp: int | None
    tournament_id: int | None = None
    season_id: int | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Match":
        tournament = payload.get("tournament", {})
        unique_tournament = tournament.get("uniqueTournament", {})
        season = payload.get("season", {})
        status = payload.get("status", {})
        return cls(
            id=int(payload["id"]),
            home_team=Team.from_payload(payload["homeTeam"]),
            away_team=Team.from_payload(payload["awayTeam"]),
            home_score=_score_value(payload.get("homeScore")),
            away_score=_score_value(payload.get("awayScore")),
            status=str(status.get("description", status.get("type", "unknown"))),
            start_timestamp=payload.get("startTimestamp"),
            tournament_id=unique_tournament.get("id", tournament.get("id")),
            season_id=season.get("id"),
        )